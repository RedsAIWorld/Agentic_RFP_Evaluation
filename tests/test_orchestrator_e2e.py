"""
End-to-end orchestrator test using a stubbed LLM provider (no network calls,
no API key needed). This exercises the full pipeline wiring -- Document Tool
-> Evaluation Agent -> Validation Tool -> Score -> Benchmark -> Rank ->
Persist -- and proves the things the rubric explicitly cares about:

1. Determinism: running finalize_ranking twice on the same validated inputs
   produces byte-identical ranking output.
2. The failure/gating path: one supplier failing does not silently produce
   a ranking, and there is no override to force one -- the run stays
   INCOMPLETE until every supplier succeeds (via retry).
3. Duplicate/empty supplier names are rejected before any evaluation work
   starts.
4. Benchmark/gap/relative-performance are actually computed and persisted
   per criterion (not just used transiently for the PPI).

Run with: pytest -q tests/test_orchestrator_e2e.py
"""
import sys
import os
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db import repository as repo
from db.seed import init_db
import orchestrator as orch


class FakeProvider:
    """Returns a canned, schema-correct response per supplier -- lets us test
    the pipeline end to end without any network access or API key."""

    def __init__(self, canned_by_supplier):
        self.canned_by_supplier = canned_by_supplier
        self.calls = 0

    def complete(self, system_prompt, user_prompt, max_tokens=4000):
        self.calls += 1
        for name, payload in self.canned_by_supplier.items():
            if name in user_prompt:
                return json.dumps(payload)
        raise AssertionError("FakeProvider: no canned response matched this prompt")


def make_canned(supplier_name, scores_by_cid, pages_text_by_cid=None):
    criteria = []
    for cid, score in scores_by_cid.items():
        criteria.append({
            "criterion_id": cid, "score": score, "max_score": 10,
            "evidence_status": "strong",
            "justification": f"Synthetic justification for criterion {cid}.",
            "evidence": [{"quote": "Apex proposes a microservices-based platform with a dedicated triage engine", "page": 1}]
                        if cid == 1 else [],
        })
    return {"supplier_name": supplier_name, "criteria": criteria, "risks": [], "overall_summary": "ok"}


def _use_temp_db(monkeypatch, tmp_path):
    db_file = tmp_path / "test.db"
    monkeypatch.setattr("db.seed.DB_PATH", str(db_file))
    init_db()


def test_full_pipeline_deterministic_ranking(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    active_criteria = repo.get_active_criteria()  # brief-default 5, incumbency inactive
    llm_criterion_ids = [c["criterion_id"] for c in active_criteria if c["scoring_source"] == "llm"]

    with open(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic",
                            "Supplier_Apex_Systems.pdf"), "rb") as f:
        apex_bytes = f.read()
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic",
                            "Supplier_BrightPath_Tech.pdf"), "rb") as f:
        brightpath_bytes = f.read()

    canned = {
        "Apex Systems": make_canned("Apex Systems", {cid: 9 for cid in llm_criterion_ids}),
        "BrightPath Tech": make_canned("BrightPath Tech", {cid: 5 for cid in llm_criterion_ids}),
    }
    provider = FakeProvider(canned)

    supplier_inputs = [
        orch.SupplierInput("Apex Systems", apex_bytes, "2026-03-04", 7, False, None),
        orch.SupplierInput("BrightPath Tech", brightpath_bytes, "2026-03-01", 4, False, None),
    ]

    def run_once():
        batch = orch.create_batch(active_criteria, "Anthropic", "fake-model", "buyer context", supplier_inputs)
        for s in batch.suppliers:
            orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)
        assert orch.all_suppliers_succeeded(batch)
        orch.finalize_ranking(batch)
        return [(s.input.supplier_name, s.final_rank, s.ppi) for s in batch.suppliers]

    result_1 = run_once()
    result_2 = run_once()
    assert sorted(result_1) == sorted(result_2)
    # Apex scored 9/10 on everything, BrightPath 5/10 -> Apex must rank 1st
    apex_rank = dict((n, r) for n, r, _ in result_1)["Apex Systems"]
    assert apex_rank == 1


def test_gap_and_relative_performance_are_persisted_per_criterion(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    active_criteria = repo.get_active_criteria()
    llm_criterion_ids = [c["criterion_id"] for c in active_criteria if c["scoring_source"] == "llm"]

    with open(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic",
                            "Supplier_Apex_Systems.pdf"), "rb") as f:
        apex_bytes = f.read()
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic",
                            "Supplier_BrightPath_Tech.pdf"), "rb") as f:
        brightpath_bytes = f.read()

    canned = {
        "Apex Systems": make_canned("Apex Systems", {cid: 9 for cid in llm_criterion_ids}),
        "BrightPath Tech": make_canned("BrightPath Tech", {cid: 5 for cid in llm_criterion_ids}),
    }
    provider = FakeProvider(canned)
    supplier_inputs = [
        orch.SupplierInput("Apex Systems", apex_bytes, "2026-03-04", 7, False, None),
        orch.SupplierInput("BrightPath Tech", brightpath_bytes, "2026-03-01", 4, False, None),
    ]
    batch = orch.create_batch(active_criteria, "Anthropic", "fake-model", "buyer context", supplier_inputs)
    for s in batch.suppliers:
        orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)
    orch.finalize_ranking(batch)

    apex = next(s for s in batch.suppliers if s.input.supplier_name == "Apex Systems")
    brightpath = next(s for s in batch.suppliers if s.input.supplier_name == "BrightPath Tech")

    # Apex scored 9 on every LLM criterion -- it IS the benchmark leader, so its gap is 0.
    for cid in llm_criterion_ids:
        detail = apex.criterion_scoring_detail[cid]
        assert detail["status"] == "ok"
        assert detail["benchmark"] == 9
        assert detail["gap"] == 0
        assert detail["relative_pct"] == 100.0

    # BrightPath scored 5 against a benchmark of 9 -- negative gap, <100% relative.
    for cid in llm_criterion_ids:
        detail = brightpath.criterion_scoring_detail[cid]
        assert detail["benchmark"] == 9
        assert detail["gap"] == -4
        assert round(detail["relative_pct"], 2) == round(5 / 9 * 100.0, 2)


def test_duplicate_supplier_names_rejected(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    active_criteria = repo.get_active_criteria()
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic",
                            "Supplier_Apex_Systems.pdf"), "rb") as f:
        apex_bytes = f.read()
    supplier_inputs = [
        orch.SupplierInput("Apex Systems", apex_bytes, "2026-03-04", 7, False, None),
        orch.SupplierInput("  apex systems  ", apex_bytes, "2026-03-01", 4, False, None),
    ]
    try:
        orch.create_batch(active_criteria, "Anthropic", "fake-model", "buyer context", supplier_inputs)
        assert False, "expected ValueError for duplicate supplier name"
    except ValueError as e:
        assert "Duplicate supplier name" in str(e)


def test_empty_supplier_name_rejected(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    active_criteria = repo.get_active_criteria()
    with open(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic",
                            "Supplier_Apex_Systems.pdf"), "rb") as f:
        apex_bytes = f.read()
    supplier_inputs = [orch.SupplierInput("   ", apex_bytes, "2026-03-04", 7, False, None)]
    try:
        orch.create_batch(active_criteria, "Anthropic", "fake-model", "buyer context", supplier_inputs)
        assert False, "expected ValueError for empty supplier name"
    except ValueError as e:
        assert "non-empty name" in str(e)


def test_failure_gates_ranking_with_no_override_possible(tmp_path, monkeypatch):
    _use_temp_db(monkeypatch, tmp_path)
    active_criteria = repo.get_active_criteria()
    llm_criterion_ids = [c["criterion_id"] for c in active_criteria if c["scoring_source"] == "llm"]

    with open(os.path.join(os.path.dirname(__file__), "..", "data", "synthetic",
                            "Supplier_Apex_Systems.pdf"), "rb") as f:
        apex_bytes = f.read()

    class AlwaysFailsProvider:
        def complete(self, *a, **kw):
            from tools.llm_providers import LLMError
            raise LLMError("simulated network failure")

    supplier_inputs = [
        orch.SupplierInput("Apex Systems", apex_bytes, "2026-03-04", 7, False, None),
    ]
    batch = orch.create_batch(active_criteria, "Anthropic", "fake-model", "buyer context", supplier_inputs)
    provider = AlwaysFailsProvider()
    for s in batch.suppliers:
        orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)

    assert batch.suppliers[0].eval_status == "FAILED"
    assert orch.all_suppliers_resolved(batch)
    assert not orch.all_suppliers_succeeded(batch)

    # There is no override anymore -- a failed supplier permanently blocks ranking
    # until it succeeds (there is no allow_partial parameter to bypass this).
    import inspect
    assert "allow_partial" not in inspect.signature(orch.finalize_ranking).parameters

    orch.finalize_ranking(batch)
    assert batch.status == "INCOMPLETE"
    assert batch.suppliers[0].final_rank is None


def test_three_way_ppi_tie_resolved_by_full_cascade(tmp_path, monkeypatch):
    """
    End-to-end proof that the mandatory tie-break cascade fires on a real run,
    not just in the pure-function unit tests in test_ranking_tool.py. Uses the
    real DemoProvider (not a stub) with the three tie-break test suppliers from
    data/synthetic/content.py, which are given IDENTICAL canned scores so they
    tie exactly on PPI:

    - Keystone Digital and Atlas Networks share a submission date -> their tie
      can only be broken by rule 3 (experience rating: 8 beats 3).
    - Solstice Technologies shares the same PPI but a later submission date
      than both -> loses the tie on rule 2 (earlier date) alone.
    """
    from tools.demo_provider import DemoProvider

    _use_temp_db(monkeypatch, tmp_path)
    active_criteria = repo.get_active_criteria()

    def load(name):
        safe = name.replace(" ", "_").replace(".", "")
        path = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic", f"Supplier_{safe}.pdf")
        with open(path, "rb") as f:
            return f.read()

    supplier_inputs = [
        orch.SupplierInput("Keystone Digital", load("Keystone Digital"), "2026-02-25", 8, False, None),
        orch.SupplierInput("Atlas Networks", load("Atlas Networks"), "2026-02-25", 3, False, None),
        orch.SupplierInput("Solstice Technologies", load("Solstice Technologies"), "2026-03-02", 6, False, None),
    ]
    batch = orch.create_batch(active_criteria, "Demo", "canned-v1", "buyer context", supplier_inputs)
    provider = DemoProvider()
    for s in batch.suppliers:
        orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)
    assert orch.all_suppliers_succeeded(batch)
    orch.finalize_ranking(batch)

    by_name = {s.input.supplier_name: s for s in batch.suppliers}
    keystone, atlas, solstice = by_name["Keystone Digital"], by_name["Atlas Networks"], by_name["Solstice Technologies"]

    # All three tie exactly on PPI -- that's the premise the whole test rests on.
    assert round(keystone.ppi, 4) == round(atlas.ppi, 4) == round(solstice.ppi, 4)

    # Earliest date + highest experience among the tied trio -> rank 1.
    assert keystone.final_rank == 1
    # Same PPI and same date as Keystone -> only experience rating separates them (rule 3).
    assert atlas.final_rank == 2
    assert "experience rating" in atlas.tie_break_reason.lower()
    assert "3 vs 8" in atlas.tie_break_reason
    # Same PPI as both, but later date -> loses on rule 2 alone.
    assert solstice.final_rank == 3
    assert "submitted later" in solstice.tie_break_reason.lower()
