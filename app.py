"""
Agentic RFP Evaluation & Supplier Ranking -- Streamlit UI.

This file is presentation only. Every number shown here was computed by
orchestrator.py / tools/ranking_tool.py -- nothing is calculated inline in
this file, which is itself part of the "LLM/UI never touches the business
math" discipline the brief asks for. Visual styling lives in ui.py.
"""
import os
import json
import datetime as dt

import streamlit as st
import plotly.graph_objects as go

from db.seed import init_db
from db import repository as repo
import orchestrator as orch
from tools.llm_providers import get_provider, LLMError, DEFAULT_MODELS, PROVIDERS
from tools.demo_provider import DemoProvider
from data.synthetic.content import BUYER_RFP, ALL_SUPPLIERS, SUGGESTED_METADATA
import ui

SYNTH_DIR = os.path.join(os.path.dirname(__file__), "data", "synthetic")

st.set_page_config(page_title="ProcureIQ | Agentic RFP Evaluation", layout="wide", page_icon="\U0001F4CB")
init_db()
st.markdown(ui.inject_css(), unsafe_allow_html=True)

CHART_FONT = dict(family="Inter, system-ui, sans-serif", color="#0b0b0b", size=13)


def style_fig(fig, height=280):
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=CHART_FONT, margin=dict(l=10, r=10, t=10, b=10), height=height,
        showlegend=False,
    )
    return fig


# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------
if "batch" not in st.session_state:
    st.session_state.batch = None
if "pending_suppliers" not in st.session_state:
    st.session_state.pending_suppliers = []


def buyer_context_text() -> str:
    return "\n\n".join(f"{h}\n{t}" for h, t in BUYER_RFP["sections"])


# ---------------------------------------------------------------------------
# Hero banner
# ---------------------------------------------------------------------------
st.markdown(
    ui.hero_banner(
        "ProcureIQ",
        "Agentic RFP Evaluation &amp; Supplier Ranking &mdash; an LLM reads and judges "
        "each proposal; Python owns every score, benchmark, and rank, end to end.",
        ["\U0001F4C4 Extract", "\U0001F916 Score (LLM)", "✅ Validate", "\U0001F3C6 Rank (deterministic)"],
    ),
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar -- AI Configuration (BYOK)
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ AI Configuration")
    demo_mode = st.checkbox(
        "Offline demo mode (no API key, no cost)",
        value=True,
        help="Uses pre-authored, realistic evaluation results for the 5 synthetic suppliers -- "
             "including a demonstration of the prompt-injection defense. Fully deterministic, "
             "zero API cost. Switch this off to use a real LLM.",
    )
    if demo_mode:
        st.markdown(
            '<div class="metric-tile" style="border-left:3px solid #0ca30c;">'
            '<div class="metric-label">Mode</div>'
            '<div class="metric-value" style="font-size:1.05rem;">\U0001F7E2 Demo Mode</div>'
            '<div class="metric-sub">Canned, realistic results. Zero API cost.</div></div>',
            unsafe_allow_html=True,
        )
        provider_name, model, api_key = "Demo", "canned-v1", ""
    else:
        st.markdown(
            '<div class="metric-tile" style="border-left:3px solid #4338CA; margin-bottom:0.6rem;">'
            '<div class="metric-label">Mode</div>'
            '<div class="metric-value" style="font-size:1.05rem;">\U0001F535 Live Mode</div>'
            '<div class="metric-sub">Calls a real LLM with your key.</div></div>',
            unsafe_allow_html=True,
        )
        provider_name = st.selectbox("Provider", list(PROVIDERS.keys()))
        model = st.text_input("Model", value=DEFAULT_MODELS[provider_name])
        api_key = st.text_input("API Key", type="password",
                                 help="Kept only in this browser session's memory -- never written to disk or the database.")
        if st.button("Test Connection", use_container_width=True):
            if not api_key:
                st.error("Enter an API key first.")
            else:
                try:
                    provider = get_provider(provider_name, api_key, model)
                    ok, msg = provider.test_connection()
                    (st.success if ok else st.error)(msg)
                except LLMError as e:
                    st.error(str(e))

    st.divider()
    if st.session_state.batch is not None:
        if st.button("\U0001F504 Start a new run", use_container_width=True):
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
    ["\U0001F4CA  Criteria", "\U0001F4E5  Supplier Input & Evaluate", "\U0001F3C6  Leaderboard",
     "\U0001F50D  Detailed Scorecards", "\U0001F4C4  Run Details"]
)

# ---------------------------------------------------------------------------
# TAB 1: Criteria
# ---------------------------------------------------------------------------
with tab_criteria:
    col_list, col_chart = st.columns([2.1, 1])

    with col_list:
        st.markdown("#### Evaluation Criteria")
        st.caption(
            "Criteria live entirely in SQLite -- nothing here is hardcoded in the prompt or scoring "
            "code. Toggling **Incumbency & Transition Cost** on deliberately pushes active weights to "
            "110%; the Ranking Tool auto-normalizes with a visible warning at the next Evaluate."
        )
        all_criteria = repo.get_all_criteria()
        edited = {}
        for i, c in enumerate(all_criteria):
            color = ui.supplier_color(i) if c["scoring_source"] == "llm" else "#4338CA"
            with st.container(border=True):
                top = st.columns([3.2, 1.3, 1, 1.2])
                source_tag = "\U0001F916 LLM-scored" if c["scoring_source"] == "llm" else "⚙️ Deterministic"
                top[0].markdown(f"**{c['name']}**  \n<span style='color:#898781;font-size:0.8rem'>{source_tag}</span>",
                                 unsafe_allow_html=True)
                new_weight = top[1].number_input("Weight %", min_value=0.0, max_value=100.0, value=float(c["weight"]),
                                                   step=1.0, key=f"weight_{c['criterion_id']}", label_visibility="collapsed")
                top[2].markdown(f"<span style='color:#898781'>max {c['max_score']}</span>", unsafe_allow_html=True)
                new_active = top[3].checkbox("Active", value=bool(c["is_active"]), key=f"active_{c['criterion_id']}")
                st.markdown(ui.bar(c["weight"], 30, color=color), unsafe_allow_html=True)
                st.caption(c["description"])
                edited[c["criterion_id"]] = (new_weight, new_active)

        if st.button("\U0001F4BE Save criteria changes", type="primary"):
            for cid, (w, a) in edited.items():
                repo.update_criterion(cid, weight=w, is_active=a)
            st.success("Saved. Active weights are re-validated and normalized (if needed) at the next Evaluate.")
            st.rerun()

    with col_chart:
        st.markdown("#### Active Weight Distribution")
        active_now = [c for c in repo.get_all_criteria() if c["is_active"]]
        total_now = sum(c["weight"] for c in active_now)
        if active_now:
            colors = [ui.supplier_color(i) if c["scoring_source"] == "llm" else "#4338CA"
                      for i, c in enumerate(active_now)]
            fig = go.Figure(go.Pie(
                labels=[c["name"] for c in active_now], values=[c["weight"] for c in active_now],
                hole=0.55, marker=dict(colors=colors, line=dict(color="#ffffff", width=2)),
                textinfo="percent", textfont=dict(size=12),
            ))
            st.plotly_chart(style_fig(fig, height=260), use_container_width=True, config={"displayModeBar": False})
        if abs(total_now - 100.0) > 1e-6:
            st.markdown(ui.metric_tile("Active Weight Total", f"{total_now:g}%", "⚠️ Will be auto-normalized"),
                        unsafe_allow_html=True)
        else:
            st.markdown(ui.metric_tile("Active Weight Total", f"{total_now:g}%", "✅ OK"), unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# TAB 2: Supplier Input & Evaluate
# ---------------------------------------------------------------------------
with tab_input:
    st.markdown("#### Supplier Proposals")
    st.caption("Prerequisite: proposals must be text-based PDFs. Scanned/image-only PDFs are not supported.")

    colA, colB = st.columns(2)
    with colA:
        with st.container(border=True):
            st.markdown("**⚡ Quick start**")
            st.caption("Loads the buyer RFP context plus all 5 synthetic supplier PDFs (4 required + 1 adversarial).")
            if st.button("Load synthetic demo batch", type="primary", use_container_width=True):
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
                st.success(f"Loaded {len(pending)} synthetic suppliers.")

    with colB:
        with st.container(border=True):
            st.markdown("**\U0001F4C1 Or upload your own**")
            uploaded_files = st.file_uploader("Supplier PDFs", type=["pdf"], accept_multiple_files=True,
                                               label_visibility="collapsed")
            if uploaded_files and st.button("Add uploaded files to batch", use_container_width=True):
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
        st.markdown("#### Supplier Batch")
        for i, s in enumerate(st.session_state.pending_suppliers):
            color = ui.supplier_color(i)
            badge = ' <span class="status-badge" style="background:#4338CA">⭐ Incumbent</span>' if s["is_incumbent"] else ""
            with st.container(border=True):
                head = st.columns([0.5, 4])
                head[0].markdown(ui.avatar(s["name"], color), unsafe_allow_html=True)
                head[1].markdown(f"**{s['name']}**{badge}", unsafe_allow_html=True)
                c1, c2, c3, c4 = st.columns(4)
                s["submission_date"] = c1.date_input("Submission date", value=dt.date.fromisoformat(s["submission_date"]),
                                                      key=f"date_{i}").isoformat()
                s["experience_rating"] = c2.slider("Experience (tie-break)", 1, 10, value=s["experience_rating"], key=f"exp_{i}")
                s["is_incumbent"] = c3.checkbox("Incumbent?", value=s["is_incumbent"], key=f"inc_{i}")
                if s["is_incumbent"]:
                    s["incumbent_performance_rating"] = c4.slider("Incumbent perf (1-5)", 1, 5,
                                                                    value=s.get("incumbent_performance_rating") or 3, key=f"incperf_{i}")
                else:
                    s["incumbent_performance_rating"] = None

        col_clear, col_eval = st.columns([1, 3])
        with col_clear:
            if st.button("\U0001F5D1️ Clear batch", use_container_width=True):
                st.session_state.pending_suppliers = []
                st.rerun()
        with col_eval:
            if st.button("▶ Evaluate Batch", type="primary", use_container_width=True):
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
                    progress.progress(i / len(batch.suppliers), text=f"Evaluating {s.input.supplier_name}...")
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
        if st.button("Finalize ranking with successful suppliers only (explicit override)"):
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
        status_color = {"COMPLETE": "#0ca30c", "INCOMPLETE": "#fab219", "FAILED": "#d03b3b"}.get(batch.status, "#898781")
        ranked = sorted([s for s in batch.suppliers if s.final_rank is not None], key=lambda s: s.final_rank)

        k1, k2, k3, k4 = st.columns(4)
        k1.markdown(ui.metric_tile("Run ID", batch.rfp_run_id[:8]), unsafe_allow_html=True)
        k2.markdown(ui.metric_tile("Status", batch.status, f'<span style="color:{status_color}">●</span> live'),
                    unsafe_allow_html=True)
        if ranked:
            k3.markdown(ui.metric_tile("Winner", ranked[0].input.supplier_name, f"PPI {ranked[0].ppi:.1f}"),
                        unsafe_allow_html=True)
            k4.markdown(ui.metric_tile("Suppliers Ranked", str(len(ranked)), f"of {len(batch.suppliers)} submitted"),
                        unsafe_allow_html=True)

        if not ranked:
            st.info("No finalized ranking yet for this run.")
        else:
            st.markdown("####")
            colors = {s.input.supplier_name: ui.supplier_color(i) for i, s in enumerate(batch.suppliers)}
            fig = go.Figure(go.Bar(
                x=[s.ppi for s in ranked][::-1], y=[s.input.supplier_name for s in ranked][::-1],
                orientation="h", marker=dict(color=[colors[s.input.supplier_name] for s in ranked][::-1]),
                text=[f"{s.ppi:.1f}" for s in ranked][::-1], textposition="outside",
            ))
            fig.update_xaxes(title="Peer Performance Index (PPI)", gridcolor="#e1e0d9", range=[0, max(s.ppi for s in ranked) * 1.18])
            fig.update_yaxes(title="")
            st.plotly_chart(style_fig(fig, height=90 + 55 * len(ranked)), use_container_width=True, config={"displayModeBar": False})

            st.markdown("#### Final Ranking")
            for s in ranked:
                idx = batch.suppliers.index(s)
                color = ui.supplier_color(idx)
                accent = ui.MEDAL_ACCENTS.get(s.final_rank, "#e1e0d9")
                incumbent_tag = ' <span class="status-badge" style="background:#4338CA">⭐ Incumbent</span>' if s.input.is_incumbent else ""
                st.markdown(f"""
<div class="rank-row" style="border-left-color:{accent}">
  <div class="rank-number">#{s.final_rank}</div>
  {ui.avatar(s.input.supplier_name, color)}
  <div style="flex:1">
    <div style="font-weight:700">{s.input.supplier_name}{incumbent_tag}</div>
    <div style="color:#52514e; font-size:0.82rem">{s.tie_break_reason or ""}</div>
  </div>
  <div style="text-align:right">
    <div style="font-weight:800; font-size:1.1rem">{s.ppi:.2f}</div>
    <div style="color:#898781; font-size:0.75rem">PPI</div>
  </div>
  <div style="text-align:right; min-width:70px">
    <div style="font-weight:700">{s.absolute_score:.1f}</div>
    <div style="color:#898781; font-size:0.75rem">Abs. score</div>
  </div>
</div>
""", unsafe_allow_html=True)

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
            choice = st.radio("Supplier", names, horizontal=True, label_visibility="collapsed")
            s = next(s for s in succeeded if s.input.supplier_name == choice)
            idx = batch.suppliers.index(s)
            color = ui.supplier_color(idx)

            head = st.columns([0.6, 3, 1, 1, 1])
            head[0].markdown(f'<div style="font-size:2.2rem">{ui.avatar(s.input.supplier_name, color)}</div>',
                              unsafe_allow_html=True)
            head[1].markdown(f"### {s.input.supplier_name}")
            if s.final_rank:
                head[2].markdown(ui.metric_tile("Rank", f"#{s.final_rank}"), unsafe_allow_html=True)
                head[3].markdown(ui.metric_tile("PPI", f"{s.ppi:.2f}"), unsafe_allow_html=True)
                head[4].markdown(ui.metric_tile("Abs. Score", f"{s.absolute_score:.1f}"), unsafe_allow_html=True)
            if s.tie_break_reason:
                st.caption(s.tie_break_reason)

            st.markdown("#### \U0001F916 LLM-Scored Criteria")
            for r in s.validated_results:
                with st.container(border=True):
                    top = st.columns([3, 1.3])
                    top[0].markdown(f"**{r.name}**  <span style='color:#898781'>&middot; weight {r.weight:g}%</span>",
                                     unsafe_allow_html=True)
                    top[1].markdown(ui.status_badge(r.evidence_status), unsafe_allow_html=True)
                    st.markdown(ui.bar(r.score, r.max_score, color=ui.SEQUENTIAL_BLUE), unsafe_allow_html=True)
                    st.markdown(f"<div style='text-align:right; font-weight:700; margin-top:2px'>{r.score}/{r.max_score}</div>",
                                unsafe_allow_html=True)
                    st.write(r.justification)
                    if r.evidence:
                        for e in r.evidence:
                            cls = "verified" if e["verified"] else "unverified"
                            icon = "✅" if e["verified"] else "⚠️ UNVERIFIED"
                            st.markdown(f'<div class="evidence-quote {cls}">{icon} p.{e["page"]}: "{e["quote"]}"</div>',
                                        unsafe_allow_html=True)
                    else:
                        st.caption("No evidence quotes cited.")
                    for w in r.warnings:
                        st.warning(w)

            if batch.deterministic_criteria:
                st.markdown("#### ⚙️ Deterministic Criteria (not scored by the LLM)")
                for d in batch.deterministic_criteria:
                    det_score, det_reason = orch.rt.score_incumbency(
                        s.input.is_incumbent, s.input.incumbent_performance_rating, d["max_score"]
                    )
                    with st.container(border=True):
                        st.markdown(f"**{d['name']}**  <span style='color:#898781'>&middot; weight {d['weight']:g}%</span>",
                                    unsafe_allow_html=True)
                        st.markdown(ui.bar(det_score, d["max_score"], color="#4338CA"), unsafe_allow_html=True)
                        st.caption(det_reason)

# ---------------------------------------------------------------------------
# TAB 5: Run Details
# ---------------------------------------------------------------------------
with tab_run:
    batch = st.session_state.batch
    if batch is None:
        st.info("No run yet.")
    else:
        st.markdown("#### Run Details")
        m1, m2, m3, m4 = st.columns(4)
        m1.markdown(ui.metric_tile("RFP_RUN_ID", batch.rfp_run_id[:8], batch.rfp_run_id), unsafe_allow_html=True)
        m2.markdown(ui.metric_tile("Status", batch.status), unsafe_allow_html=True)
        m3.markdown(ui.metric_tile("Provider / Model", batch.provider_name, batch.model), unsafe_allow_html=True)
        m4.markdown(ui.metric_tile("Created (UTC)", batch.created_at[:19].replace("T", " ")), unsafe_allow_html=True)

        if batch.weight_warning:
            st.warning(f"Weight normalization: {batch.weight_warning}")

        st.markdown("#### Criteria snapshot used for this run")
        st.dataframe(batch.criteria_snapshot, use_container_width=True, hide_index=True)

        st.markdown("#### Warnings ledger")
        any_warning = False
        for s in batch.suppliers:
            for w in s.run_warnings:
                any_warning = True
                icon = "\U0001F534" if "hallucination" in w.lower() or "unverif" in w.lower() else \
                       "\U0001F7E0" if "clip" in w.lower() or "normaliz" in w.lower() or "missing" in w.lower() else "ℹ️"
                st.markdown(f"{icon} **{s.input.supplier_name}**: {w}")
            if s.error_message:
                any_warning = True
                st.markdown(f"\U0001F534 **{s.input.supplier_name}** (FAILED): {s.error_message}")
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
