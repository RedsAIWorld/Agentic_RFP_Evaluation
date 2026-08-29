"""
Orchestrator -- the Agentic Design's control plane (brief Section 3).

This is a plain Python DAG, not a framework-managed agent. It is written to
a graph contract on purpose (RunState threaded through, steps declared in
order, each step's inputs/outputs typed) so it reads like the agentic
pipeline the brief asks for, without pulling in a graph runtime for a fixed,
non-branching pipeline that doesn't need one.

Step order (mirrors brief Section 4):
  Setup -> Input -> Batch -> Evaluate (per supplier: Document Tool ->
  Evaluation Agent -> Validation Tool) -> Score -> Benchmark -> Rank ->
  Persist -> Present

Tool-boundary discipline (the project's central thesis, enforced by types
here, not just by convention):
  - evaluation_agent.evaluate_supplier() takes an LLM provider and returns
    a raw dict. It never sees other suppliers' data and never touches
    weights, benchmarks, or ranks.
  - ranking_tool functions take no LLM provider argument at all -- it is
    structurally impossible for them to call an LLM.
"""
import uuid
import datetime as dt
from dataclasses import dataclass, field

from tools.document_tool import extract_pdf
from tools.evaluation_agent import evaluate_supplier
from tools.llm_providers import LLMError
from tools.validation_tool import validate_supplier_result
from tools import ranking_tool as rt
from db import repository as repo


MAX_AUTO_RETRIES = 1  # one automatic retry, then it's a manual "Retry" action (locked decision H)


@dataclass
class SupplierInput:
    supplier_name: str
    file_bytes: bytes
    submission_date: str
    experience_rating: int
    is_incumbent: bool
    incumbent_performance_rating: int | None


@dataclass
class SupplierRunState:
    input: SupplierInput
    extraction: object = None
    raw_llm_result: dict = None
    validated_results: list = None
    run_warnings: list = field(default_factory=list)
    eval_status: str = "PENDING"   # PENDING | SUCCESS | FAILED
    attempts: int = 0
    error_message: str = None
    absolute_score: float = None
    ppi: float = None
    final_rank: int = None
    tie_break_reason: str = None
    criterion_scoring_detail: dict = field(default_factory=dict)  # criterion_id -> {benchmark, gap, relative_pct, status}


@dataclass
class BatchRunState:
    rfp_run_id: str
    created_at: str
    criteria_snapshot: list        # ALL active criteria (llm + deterministic), pre-normalization
    llm_criteria: list             # active, scoring_source='llm', normalized weights
    deterministic_criteria: list   # active, scoring_source='deterministic', normalized weights
    weight_warning: str
    provider_name: str
    model: str
    buyer_context: str
    suppliers: list                # list[SupplierRunState]
    status: str = "IN_PROGRESS"    # IN_PROGRESS | INCOMPLETE | COMPLETE | FAILED


def create_batch(active_criteria: list, provider_name: str, model: str, buyer_context: str,
                  supplier_inputs: list) -> BatchRunState:
    """Step: Setup + Batch. Snapshots criteria ONCE here -- every supplier in
    this run is scored against exactly this snapshot, even if the criteria
    table changes mid-run in another browser tab (locked decision).

    Raises ValueError before any DB write if the criteria configuration is
    nonsensical (review #4) or if supplier names are missing/duplicated
    within this batch (review #5) -- both are configuration errors, not
    evaluation failures, so they fail fast rather than surfacing later as a
    confusing per-supplier FAILED status."""
    rt.validate_criteria_configuration(active_criteria)

    seen_names = {}
    for s in supplier_inputs:
        cleaned = (s.supplier_name or "").strip()
        if not cleaned:
            raise ValueError("Every supplier must have a non-empty name.")
        s.supplier_name = cleaned
        key = cleaned.lower()
        if key in seen_names:
            raise ValueError(
                f"Duplicate supplier name in this batch: '{cleaned}' and '{seen_names[key]}' -- "
                f"supplier names must be unique within a run."
            )
        seen_names[key] = cleaned

    normalized_all, weight_warning = rt.normalize_weights(active_criteria)
    llm_criteria = [c for c in normalized_all if c["scoring_source"] == "llm"]
    deterministic_criteria = [c for c in normalized_all if c["scoring_source"] == "deterministic"]

    rfp_run_id = str(uuid.uuid4())
    created_at = dt.datetime.now(dt.timezone.utc).isoformat()

    state = BatchRunState(
        rfp_run_id=rfp_run_id,
        created_at=created_at,
        criteria_snapshot=normalized_all,
        llm_criteria=llm_criteria,
        deterministic_criteria=deterministic_criteria,
        weight_warning=weight_warning,
        provider_name=provider_name,
        model=model,
        buyer_context=buyer_context,
        suppliers=[SupplierRunState(input=s) for s in supplier_inputs],
    )
    repo.create_run(rfp_run_id, created_at, normalized_all, provider_name, model, weight_warning)
    return state


def run_evaluation_for_supplier(supplier_state: SupplierRunState, llm_criteria: list,
                                 buyer_context: str, provider) -> None:
    """
    Step: Evaluate + Validate, for ONE supplier. Mutates supplier_state in
    place. Implements the auto-retry-once-then-stop policy (locked decision H).
    Never raises -- failures are recorded on the state so the orchestrator can
    continue with other suppliers.
    """
    inp = supplier_state.input
    supplier_state.attempts += 1

    # --- Document Tool ---
    extraction = extract_pdf(inp.file_bytes, inp.supplier_name)
    supplier_state.extraction = extraction
    if not extraction.is_usable:
        supplier_state.eval_status = "FAILED"
        supplier_state.error_message = extraction.warning
        return

    # --- Evaluation Agent (with one automatic retry on failure) ---
    last_error = None
    for attempt in range(MAX_AUTO_RETRIES + 1):
        try:
            raw = evaluate_supplier(provider, llm_criteria, inp.supplier_name,
                                     extraction.full_text, buyer_context)
            supplier_state.raw_llm_result = raw
            last_error = None
            break
        except (LLMError, ValueError) as e:
            last_error = str(e)
            supplier_state.attempts += 1

    if last_error is not None:
        supplier_state.eval_status = "FAILED"
        supplier_state.error_message = (
            f"LLM evaluation failed after {supplier_state.attempts} attempt(s): {last_error}"
        )
        return

    # --- Validation Tool ---
    validated_results, warnings = validate_supplier_result(
        supplier_state.raw_llm_result, llm_criteria, extraction.pages
    )
    supplier_state.validated_results = validated_results
    supplier_state.run_warnings.extend(warnings)
    supplier_state.eval_status = "SUCCESS"


def retry_supplier(batch: BatchRunState, supplier_name: str, provider) -> None:
    """Manual retry action (the '[Retry Failed Supplier]' button)."""
    for s in batch.suppliers:
        if s.input.supplier_name == supplier_name:
            run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)
            return
    raise ValueError(f"Supplier not found in this run: {supplier_name}")


def all_suppliers_resolved(batch: BatchRunState) -> bool:
    return all(s.eval_status in ("SUCCESS", "FAILED") for s in batch.suppliers)


def all_suppliers_succeeded(batch: BatchRunState) -> bool:
    return all(s.eval_status == "SUCCESS" for s in batch.suppliers)


def finalize_ranking(batch: BatchRunState) -> None:
    """
    Step: Score -> Benchmark -> Rank -> Persist.

    Gating (re-confirmed decision, superseding the earlier "hybrid" override):
    this function NEVER computes a ranking unless every supplier succeeded.
    There is no override path -- a run with any failed supplier stays
    INCOMPLETE until that supplier succeeds (via retry) or is removed from
    the batch. All suppliers are still evaluated up front (the orchestrator
    never stops early on the first failure); this gate only governs whether
    a rank is ever produced.
    """
    if not all_suppliers_resolved(batch):
        raise RuntimeError("Cannot finalize: not every supplier has finished evaluating (pending attempts).")

    succeeded = [s for s in batch.suppliers if s.eval_status == "SUCCESS"]
    failed = [s for s in batch.suppliers if s.eval_status == "FAILED"]

    if failed:
        batch.status = "INCOMPLETE"
        repo.set_run_status(batch.rfp_run_id, "INCOMPLETE")
        # Persist failed suppliers' state so the UI can show why, without ranking anyone.
        for s in failed:
            repo.upsert_supplier_result(
                batch.rfp_run_id, s.input.supplier_name, s.input.submission_date,
                s.input.experience_rating, s.input.is_incumbent, s.input.incumbent_performance_rating,
                "FAILED", warnings=[s.error_message] if s.error_message else [],
                result_payload={"error": s.error_message},
            )
        return

    # --- Score: absolute weighted score per supplier (LLM-scored + deterministic criteria) ---
    all_supplier_criterion_scores = {}
    for s in succeeded:
        scores_by_cid = {r.criterion_id: r.score for r in s.validated_results}
        for det in batch.deterministic_criteria:
            det_score, det_reason = rt.score_incumbency(
                s.input.is_incumbent, s.input.incumbent_performance_rating, det["max_score"]
            )
            scores_by_cid[det["criterion_id"]] = det_score
            s.run_warnings.append(f"[{det['name']}] {det_reason} (score: {det_score}/{det['max_score']})")
        s.absolute_score = rt.compute_absolute_score(scores_by_cid, batch.criteria_snapshot)
        all_supplier_criterion_scores[s.input.supplier_name] = scores_by_cid

    # --- Benchmark (per criterion, across succeeded suppliers only) ---
    benchmarks = rt.compute_benchmarks(all_supplier_criterion_scores, batch.criteria_snapshot)

    excluded_criterion_ids = {cid for cid, b in benchmarks.items() if b["status"] == "no_valid_scores"}

    criteria_name_by_id = {c["criterion_id"]: c["name"] for c in batch.criteria_snapshot}

    for s in succeeded:
        scores_by_cid = all_supplier_criterion_scores[s.input.supplier_name]
        rel_perf = {}
        scoring_detail = {}
        for c in batch.criteria_snapshot:
            cid = c["criterion_id"]
            supplier_val = scores_by_cid.get(cid, 0)
            if cid in excluded_criterion_ids:
                scoring_detail[cid] = {
                    "benchmark": None, "gap": None, "relative_pct": None, "status": "no_valid_scores",
                }
                continue
            benchmark_val = benchmarks[cid]["benchmark"]
            rel, warn = rt.compute_relative_performance(supplier_val, benchmark_val)
            gap = rt.compute_criterion_gap(supplier_val, benchmark_val)
            rel_perf[cid] = rel
            scoring_detail[cid] = {
                "benchmark": benchmark_val, "gap": gap, "relative_pct": rel, "status": "ok",
            }
            if warn:
                s.run_warnings.append(f"[{c['name']}] {warn}")
        s.criterion_scoring_detail = scoring_detail
        ppi, ppi_warnings = rt.compute_ppi(rel_perf, batch.criteria_snapshot, excluded_criterion_ids)
        s.ppi = ppi
        s.run_warnings.extend(ppi_warnings)

    # --- Tie-break + Rank ---
    ranking_input = [
        {"supplier_name": s.input.supplier_name, "submission_date": s.input.submission_date,
         "experience_rating": s.input.experience_rating, "ppi": s.ppi}
        for s in succeeded
    ]
    ranked = rt.rank_suppliers(ranking_input)
    rank_by_name = {r["supplier_name"]: r for r in ranked}
    for s in succeeded:
        r = rank_by_name[s.input.supplier_name]
        s.final_rank = r["final_rank"]
        s.tie_break_reason = r["tie_break_reason"]

    # --- Persist ---
    for s in succeeded:
        result_payload = {
            "supplier_name": s.input.supplier_name,
            "raw_llm_result": s.raw_llm_result,
            "validated_criteria": [vars(r) for r in s.validated_results],
            "deterministic_criteria": [
                {"criterion_id": d["criterion_id"], "name": d["name"],
                 "score": all_supplier_criterion_scores[s.input.supplier_name][d["criterion_id"]],
                 "max_score": d["max_score"]}
                for d in batch.deterministic_criteria
            ],
            "criterion_scoring_detail": [
                {"criterion_id": cid, "name": criteria_name_by_id.get(cid), **detail}
                for cid, detail in s.criterion_scoring_detail.items()
            ],
            "absolute_score": s.absolute_score,
            "ppi": s.ppi,
            "final_rank": s.final_rank,
            "tie_break_reason": s.tie_break_reason,
            "criteria_snapshot": batch.criteria_snapshot,
            "benchmarks": benchmarks,
            "warnings": s.run_warnings,
        }
        repo.upsert_supplier_result(
            batch.rfp_run_id, s.input.supplier_name, s.input.submission_date,
            s.input.experience_rating, s.input.is_incumbent, s.input.incumbent_performance_rating,
            "SUCCESS", absolute_score=s.absolute_score, ppi=s.ppi, final_rank=s.final_rank,
            warnings=s.run_warnings, result_payload=result_payload,
        )

    batch.status = "COMPLETE"
    repo.set_run_status(batch.rfp_run_id, "COMPLETE")
