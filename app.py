"""
Agentic RFP Evaluation & Supplier Ranking -- Streamlit UI.

This file is presentation only. Every number shown here was computed by
orchestrator.py / tools/ranking_tool.py -- nothing is calculated inline in
this file, which is itself part of the "LLM/UI never touches the business
math" discipline the brief asks for.
"""
import os
import json
import datetime as dt

import streamlit as st

from db.seed import init_db
from db import repository as repo
import orchestrator as orch
from tools.llm_providers import get_provider, LLMError, DEFAULT_MODELS, PROVIDERS
from tools.demo_provider import DemoProvider
from data.synthetic.content import BUYER_RFP, ALL_SUPPLIERS, SUGGESTED_METADATA

SYNTH_DIR = os.path.join(os.path.dirname(__file__), "data", "synthetic")

st.set_page_config(page_title="Agentic RFP Evaluation", layout="wide")
init_db()

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "batch" not in st.session_state:
    st.session_state.batch = None
if "pending_suppliers" not in st.session_state:
    st.session_state.pending_suppliers = []  # list of dicts: name, bytes, submission_date, experience_rating, is_incumbent, incumbent_performance_rating


def buyer_context_text() -> str:
    return "\n\n".join(f"{h}\n{t}" for h, t in BUYER_RFP["sections"])


# ---------------------------------------------------------------------------
# Sidebar -- AI Configuration (BYOK)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("AI Configuration")
    demo_mode = st.checkbox(
        "Offline demo mode (no API key, no cost)",
        value=True,
        help="Uses pre-authored, realistic evaluation results for the 5 synthetic suppliers -- "
             "including a demonstration of the prompt-injection defense. Fully deterministic, "
             "zero API cost. Switch this off to use a real LLM.",
    )
    if not demo_mode:
        provider_name = st.selectbox("Provider", list(PROVIDERS.keys()))
        model = st.text_input("Model", value=DEFAULT_MODELS[provider_name])
        api_key = st.text_input("API Key", type="password",
                                 help="Kept only in this browser session's memory -- never written to disk or the database.")
        if st.button("Test Connection"):
            if not api_key:
                st.error("Enter an API key first.")
            else:
                try:
                    provider = get_provider(provider_name, api_key, model)
                    ok, msg = provider.test_connection()
                    (st.success if ok else st.error)(msg)
                except LLMError as e:
                    st.error(str(e))
    else:
        provider_name, model, api_key = "Demo", "canned-v1", ""
        st.caption("Demo mode active -- every 'AI' criterion score below comes from a fixed, "
                   "pre-authored canned response, not a live model call.")

    st.divider()
    if st.session_state.batch is not None:
        if st.button("Start a new run (clear current results)"):
            st.session_state.batch = None
            st.session_state.pending_suppliers = []
            st.rerun()


def get_active_provider():
    if demo_mode:
        return DemoProvider()
    return get_provider(provider_name, api_key, model)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------
tab_criteria, tab_input, tab_leaderboard, tab_scorecards, tab_run = st.tabs(
    ["1. Criteria", "2. Supplier Input & Evaluate", "3. Leaderboard", "4. Detailed Scorecards", "5. Run Details"]
)

# ---------------------------------------------------------------------------
# TAB 1: Criteria
# ---------------------------------------------------------------------------
with tab_criteria:
    st.subheader("Evaluation Criteria")
    st.caption(
        "Criteria live entirely in SQLite -- nothing here is hardcoded in the prompt or scoring "
        "code. Toggling 'Incumbency & Transition Cost' on deliberately pushes active weights to "
        "110%; the Ranking Tool detects this at the next Evaluate and auto-normalizes with a "
        "visible warning (see Run Details after a run)."
    )
    all_criteria = repo.get_all_criteria()
    active_weight_sum = sum(c["weight"] for c in all_criteria if c["is_active"])

    edited = {}
    for c in all_criteria:
        cols = st.columns([3, 1.2, 1, 1.3, 4])
        cols[0].markdown(f"**{c['name']}**  \n*{c['scoring_source']}*")
        new_weight = cols[1].number_input(
            "Weight %", min_value=0.0, max_value=100.0, value=float(c["weight"]),
            step=1.0, key=f"weight_{c['criterion_id']}", label_visibility="collapsed",
        )
        cols[2].markdown(f"max {c['max_score']}")
        new_active = cols[3].checkbox("Active", value=bool(c["is_active"]), key=f"active_{c['criterion_id']}")
        cols[4].caption(c["description"])
        edited[c["criterion_id"]] = (new_weight, new_active)

    if st.button("Save criteria changes"):
        for cid, (w, a) in edited.items():
            repo.update_criterion(cid, weight=w, is_active=a)
        st.success("Saved. Active weights are re-validated and normalized (if needed) at the next Evaluate.")
        st.rerun()

    active_now = [c for c in repo.get_all_criteria() if c["is_active"]]
    total_now = sum(c["weight"] for c in active_now)
    if abs(total_now - 100.0) > 1e-6:
        st.warning(f"Active weights currently sum to {total_now:g}%, not 100% -- will be "
                   f"auto-normalized (with a logged warning) the next time you run Evaluate.")
    else:
        st.info(f"Active weights sum to {total_now:g}%. OK.")

# ---------------------------------------------------------------------------
# TAB 2: Supplier Input & Evaluate
# ---------------------------------------------------------------------------
with tab_input:
    st.subheader("Supplier Proposals")
    st.caption("Prerequisite: proposals must be text-based PDFs. Scanned/image-only PDFs are not supported.")

    colA, colB = st.columns([1, 1])
    with colA:
        if st.button("Load synthetic demo batch (Buyer RFP + 5 suppliers)"):
            pending = []
            for supplier in ALL_SUPPLIERS:
                safe_name = supplier["supplier_name"].replace(" ", "_").replace(".", "")
                path = os.path.join(SYNTH_DIR, f"Supplier_{safe_name}.pdf")
                with open(path, "rb") as f:
                    file_bytes = f.read()
                meta = SUGGESTED_METADATA[supplier["supplier_name"]]
                pending.append({
                    "name": supplier["supplier_name"], "bytes": file_bytes,
                    "submission_date": meta["submission_date"],
                    "experience_rating": meta["experience_rating"],
                    "is_incumbent": meta["is_incumbent"],
                    "incumbent_performance_rating": meta["incumbent_performance_rating"],
                })
            st.session_state.pending_suppliers = pending
            st.success(f"Loaded {len(pending)} synthetic suppliers. Review metadata below, then click Evaluate.")

    with colB:
        uploaded_files = st.file_uploader("Or upload your own supplier PDFs", type=["pdf"], accept_multiple_files=True)
        if uploaded_files and st.button("Add uploaded files to batch"):
            pending = list(st.session_state.pending_suppliers)
            for uf in uploaded_files:
                pending.append({
                    "name": os.path.splitext(uf.name)[0], "bytes": uf.read(),
                    "submission_date": dt.date.today().isoformat(),
                    "experience_rating": 5, "is_incumbent": False,
                    "incumbent_performance_rating": None,
                })
            st.session_state.pending_suppliers = pending
            st.rerun()

    if st.session_state.pending_suppliers:
        st.markdown("#### Supplier metadata (edit as needed)")
        for i, s in enumerate(st.session_state.pending_suppliers):
            with st.expander(f"{s['name']}", expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                s["submission_date"] = c1.date_input(
                    "Submission date", value=dt.date.fromisoformat(s["submission_date"]),
                    key=f"date_{i}").isoformat()
                s["experience_rating"] = c2.slider("Historical experience (1-10, tie-break only)", 1, 10,
                                                     value=s["experience_rating"], key=f"exp_{i}")
                s["is_incumbent"] = c3.checkbox("Incumbent supplier?", value=s["is_incumbent"], key=f"inc_{i}")
                if s["is_incumbent"]:
                    s["incumbent_performance_rating"] = c4.slider(
                        "Incumbent performance (1-5)", 1, 5,
                        value=s.get("incumbent_performance_rating") or 3, key=f"incperf_{i}")
                else:
                    s["incumbent_performance_rating"] = None

        if st.button("🗑️ Clear supplier batch"):
            st.session_state.pending_suppliers = []
            st.rerun()

        st.divider()
        if st.button("▶ Evaluate Batch", type="primary"):
            active_criteria = repo.get_active_criteria()
            supplier_inputs = [
                orch.SupplierInput(
                    supplier_name=s["name"], file_bytes=s["bytes"],
                    submission_date=s["submission_date"], experience_rating=s["experience_rating"],
                    is_incumbent=s["is_incumbent"],
                    incumbent_performance_rating=s["incumbent_performance_rating"],
                )
                for s in st.session_state.pending_suppliers
            ]
            try:
                provider = get_active_provider()
            except LLMError as e:
                st.error(str(e))
                st.stop()

            batch = orch.create_batch(active_criteria, provider_name if not demo_mode else "Demo",
                                       model if not demo_mode else "canned-v1",
                                       buyer_context_text(), supplier_inputs)
            if batch.weight_warning:
                st.warning(batch.weight_warning)

            progress = st.progress(0.0, text="Starting evaluation...")
            for i, s in enumerate(batch.suppliers):
                progress.progress((i) / len(batch.suppliers), text=f"Evaluating {s.input.supplier_name}...")
                orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)
            progress.progress(1.0, text="Evaluation complete.")

            st.session_state.batch = batch
            if orch.all_suppliers_succeeded(batch):
                orch.finalize_ranking(batch)
                st.success("All suppliers evaluated successfully. Ranking finalized -- see the Leaderboard tab.")
            else:
                st.session_state.batch.status = "INCOMPLETE"
                st.warning("One or more suppliers failed evaluation. See below to retry or finalize a partial ranking.")
            st.rerun()
    else:
        st.info("Load the synthetic demo batch, or upload your own PDFs, to begin.")

    # Post-evaluation failure handling (retry / override), shown right where the workflow continues
    batch = st.session_state.batch
    if batch is not None and not orch.all_suppliers_succeeded(batch):
        st.divider()
        st.markdown("#### ⚠️ Some suppliers failed evaluation")
        failed = [s for s in batch.suppliers if s.eval_status == "FAILED"]
        succeeded = [s for s in batch.suppliers if s.eval_status == "SUCCESS"]
        st.write(f"**{len(succeeded)} succeeded, {len(failed)} failed** (out of {len(batch.suppliers)}). "
                 f"Successful evaluations are cached -- no ranking will be computed until every "
                 f"supplier succeeds, or you explicitly finalize with a partial set.")
        for s in failed:
            st.error(f"**{s.input.supplier_name}**: {s.error_message}")
            if st.button(f"Retry {s.input.supplier_name}", key=f"retry_{s.input.supplier_name}"):
                provider = get_active_provider()
                orch.retry_supplier(batch, s.input.supplier_name, provider)
                if orch.all_suppliers_succeeded(batch):
                    orch.finalize_ranking(batch)
                st.rerun()
        if st.button("Finalize ranking with successful suppliers only (explicit override)", type="secondary"):
            orch.finalize_ranking(batch, allow_partial=True)
            st.rerun()

# ---------------------------------------------------------------------------
# TAB 3: Leaderboard
# ---------------------------------------------------------------------------
with tab_leaderboard:
    batch = st.session_state.batch
    if batch is None:
        st.info("No run yet -- go to 'Supplier Input & Evaluate' to start one.")
    else:
        st.subheader(f"Leaderboard -- Run `{batch.rfp_run_id[:8]}`")
        st.caption(f"Status: **{batch.status}**  |  Provider: {batch.provider_name} / {batch.model}")
        ranked = sorted([s for s in batch.suppliers if s.final_rank is not None], key=lambda s: s.final_rank)
        if not ranked:
            st.info("No finalized ranking yet for this run.")
        else:
            rows = []
            for s in ranked:
                rows.append({
                    "Rank": s.final_rank, "Supplier": s.input.supplier_name,
                    "Absolute Score": round(s.absolute_score, 2), "PPI": round(s.ppi, 4),
                    "Submission Date": s.input.submission_date, "Experience (tie-break)": s.input.experience_rating,
                    "Incumbent": "Yes" if s.input.is_incumbent else "No",
                    "Tie-break reason": s.tie_break_reason,
                })
            st.dataframe(rows, use_container_width=True, hide_index=True)

# ---------------------------------------------------------------------------
# TAB 4: Detailed Scorecards
# ---------------------------------------------------------------------------
with tab_scorecards:
    batch = st.session_state.batch
    if batch is None:
        st.info("No run yet.")
    else:
        succeeded = [s for s in batch.suppliers if s.eval_status == "SUCCESS"]
        if not succeeded:
            st.info("No successfully evaluated suppliers yet.")
        else:
            names = [s.input.supplier_name for s in succeeded]
            choice = st.selectbox("Supplier", names)
            s = next(s for s in succeeded if s.input.supplier_name == choice)

            st.markdown(f"### {s.input.supplier_name}")
            if s.final_rank:
                st.markdown(f"**Rank {s.final_rank}** &nbsp;|&nbsp; Absolute score: **{s.absolute_score:.2f}** "
                            f"&nbsp;|&nbsp; PPI: **{s.ppi:.4f}**")
                st.caption(s.tie_break_reason or "")

            st.markdown("#### LLM-Scored Criteria")
            for r in s.validated_results:
                with st.container(border=True):
                    st.markdown(f"**{r.name}** — score **{r.score}/{r.max_score}** "
                                f"(weight {r.weight:g}%) — evidence quality: `{r.evidence_status}`")
                    st.write(r.justification)
                    if r.evidence:
                        for e in r.evidence:
                            icon = "✅" if e["verified"] else "⚠️ UNVERIFIED"
                            st.caption(f"{icon} p.{e['page']}: \"{e['quote']}\"")
                    else:
                        st.caption("No evidence quotes cited.")
                    if r.warnings:
                        for w in r.warnings:
                            st.warning(w)

            if batch.deterministic_criteria:
                st.markdown("#### Deterministic Criteria (not scored by the LLM)")
                for d in batch.deterministic_criteria:
                    det_score, det_reason = orch.rt.score_incumbency(
                        s.input.is_incumbent, s.input.incumbent_performance_rating, d["max_score"]
                    ) if hasattr(orch, "rt") else (None, None)
                    st.info(f"**{d['name']}** (weight {d['weight']:g}%): {det_reason}")

# ---------------------------------------------------------------------------
# TAB 5: Run Details
# ---------------------------------------------------------------------------
with tab_run:
    batch = st.session_state.batch
    if batch is None:
        st.info("No run yet.")
    else:
        st.subheader("Run Details")
        st.write(f"**RFP_RUN_ID:** `{batch.rfp_run_id}`")
        st.write(f"**Created (UTC):** {batch.created_at}")
        st.write(f"**Status:** {batch.status}")
        st.write(f"**Provider / Model:** {batch.provider_name} / {batch.model}")
        if batch.weight_warning:
            st.warning(f"Weight normalization: {batch.weight_warning}")

        st.markdown("#### Criteria snapshot used for this run")
        st.dataframe(batch.criteria_snapshot, use_container_width=True, hide_index=True)

        st.markdown("#### Warnings ledger (all suppliers)")
        any_warning = False
        for s in batch.suppliers:
            for w in s.run_warnings:
                any_warning = True
                st.write(f"- **{s.input.supplier_name}**: {w}")
            if s.error_message:
                any_warning = True
                st.write(f"- **{s.input.supplier_name}** (FAILED): {s.error_message}")
        if not any_warning:
            st.caption("No warnings recorded for this run.")

        st.markdown("#### Export")
        export_payload = {
            "rfp_run_id": batch.rfp_run_id,
            "created_at": batch.created_at,
            "status": batch.status,
            "provider": batch.provider_name,
            "model": batch.model,
            "criteria_snapshot": batch.criteria_snapshot,
            "suppliers": [
                {
                    "supplier_name": s.input.supplier_name,
                    "eval_status": s.eval_status,
                    "absolute_score": s.absolute_score,
                    "ppi": s.ppi,
                    "final_rank": s.final_rank,
                    "tie_break_reason": s.tie_break_reason,
                    "warnings": s.run_warnings,
                    "criteria_results": [vars(r) for r in (s.validated_results or [])],
                    "error_message": s.error_message,
                }
                for s in batch.suppliers
            ],
        }
        st.download_button(
            "⬇ Download complete run as JSON",
            data=json.dumps(export_payload, indent=2, default=str),
            file_name=f"rfp_run_{batch.rfp_run_id[:8]}.json",
            mime="application/json",
        )
