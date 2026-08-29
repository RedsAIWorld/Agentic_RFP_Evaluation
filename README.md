# Agentic RFP Evaluation and Supplier Ranking

An AI-assisted application that reads supplier RFP proposals, scores them against
configurable criteria, benchmarks suppliers against their peers, and produces an
explainable, deterministic final leaderboard.

**Built for:** IIT Roorkee Agentic AI programme — classroom mini project.

## The one rule everything else follows

> The LLM may judge proposal content. It must never decide arithmetic, benchmarks,
> tie-breaks, or rank.

Concretely: the LLM returns a score (0–10) and a cited quote per criterion, as JSON.
Every weighted score, peer benchmark, gap, relative percentage, Peer Performance
Index (PPI), tie-break, and rank is computed by pure Python in `tools/ranking_tool.py`
— a file that has no LLM client, no API import, and cannot call one. That is
enforced by the function signatures, not just by convention.

## Quick start

```bash
pip install -r requirements.txt
python3 db/seed.py                       # creates & seeds rfp_evaluation.db
python3 data/synthetic/render_pdfs.py    # (re)generates the 6 synthetic PDFs
streamlit run app.py
```

Open the app, tick **"Offline demo mode"** in the sidebar (on by default), click
**"Load synthetic demo batch"** in the Supplier Input tab, then **Evaluate Batch**.
The whole pipeline runs with zero API calls and zero cost, using pre-authored,
realistic evaluation results — see "Demo mode" below for why this exists.

To use a real model instead, untick demo mode, pick a provider, paste an API key
(kept only in browser session memory, never written to disk or the database), and
click **Test Connection** before evaluating.

Run the test suite:
```bash
pytest -q            # 15 tests: pure ranking-tool math + full pipeline wiring
python3 scripts/demo_run.py   # runs the full pipeline outside Streamlit, prints the leaderboard
```

## Agentic design

| Component | Responsibility | Lives in |
|---|---|---|
| Orchestrator | Controls the workflow, calls tools in a fixed order, owns retry/gating | `orchestrator.py` |
| Document Tool | Extracts clean, **page-mapped** text from each uploaded PDF | `tools/document_tool.py` |
| Evaluation Agent | Uses active criteria to score ONE supplier, cites evidence | `tools/evaluation_agent.py` |
| LLM Provider | Vendor-agnostic HTTP client (Anthropic / OpenAI / Demo) | `tools/llm_providers.py`, `tools/demo_provider.py` |
| Validation Tool | Schema check, fill/clip, evidence-quote verification | `tools/validation_tool.py` |
| Ranking Tool | ALL arithmetic: score, benchmark, PPI, tie-break, rank | `tools/ranking_tool.py` |

**Why a plain Python orchestrator instead of a graph framework** (e.g. LangGraph):
this workflow is a fixed pipeline with a per-supplier fan-out — every run executes
the same steps in the same order, it never re-plans itself. That is a DAG, not an
autonomous agent deciding its own control flow, so `orchestrator.py` is written
*to* a graph contract (a single typed `RunState` threaded through named, ordered
steps) without the runtime weight of a graph engine. A graph framework would earn
its keep if this workflow needed durable checkpoints, human-in-the-loop pauses, or
dynamic re-planning — it doesn't. The `Step`-shaped functions in `orchestrator.py`
could be lifted into LangGraph nodes in well under a day if that ever changes.

```
Setup (load criteria) -> Input (upload + metadata) -> Batch (snapshot criteria, new RFP_RUN_ID)
   -> for each supplier: Document Tool -> Evaluation Agent -> Validation Tool
   -> gate: all succeeded? -----------------------------------------+
        no -> INCOMPLETE, show retry / explicit partial-finalize -> |
        yes ------------------------------------------------------>+
                                                                      v
                                          Score -> Benchmark -> PPI -> Tie-break -> Rank -> Persist -> Present
```

## Database schema

Extends the brief's minimum design (Section 6) with fields required for
reproducibility and auditability — see `db/schema.sql` for the full DDL.

- **`evaluation_criteria`**: `criterion_id, name, description, weight, max_score, scoring_source, is_active`.
  `scoring_source` is `'llm'` or `'deterministic'` — see Incumbency below.
- **`rfp_runs`**: `rfp_run_id, created_at, status, criteria_snapshot_json, provider, model, weight_warning`.
  The criteria snapshot is frozen **once, at batch creation** — if someone edits
  weights mid-run in another tab, this run is unaffected; the next run picks up
  the change. `provider`/`model` are recorded; the API key never is.
- **`supplier_results`**: one row per supplier per run — metadata, `absolute_score`,
  `ppi`, `final_rank`, `warnings_json` (structured), and `result_json` (the complete
  raw LLM response + validated criteria + scoring breakdown — the single source of
  truth every displayed number is traceable back to).

## Evaluation criteria (seeded defaults)

| Criterion | Weight | Source | Active by default? |
|---|---|---|---|
| Technical Capability | 30% | LLM | Yes |
| Implementation Plan | 20% | LLM | Yes |
| Commercial Value | 20% | LLM | Yes |
| Security & Compliance | 20% | LLM | Yes |
| Support & Experience | 10% | LLM | Yes |
| Incumbency & Transition Cost | 10% | **Deterministic** | **No** (see below) |

The app boots in exact brief-compliance mode (the five LLM criteria sum to 100%).
Toggling Incumbency on in the Criteria tab deliberately pushes active weights to
110% — a live, harmless demonstration of the weight-normalization rule below.

## Formulas (worked example, from an actual demo-mode run)

- **Absolute weighted score** = Σ (criterion_score / max_score) × weight.
  NexaWorks: Technical 8/10×30 + Implementation 10/10×20 + Commercial 8/10×20 +
  Security 9/10×20 + Support 9/10×10 = 24+20+16+18+9 = **87.00**.
- **Criterion benchmark** = highest valid score observed for that criterion, across
  all successfully evaluated suppliers in this run.
- **Criterion gap** = supplier score − benchmark (0 for the leader, negative otherwise).
- **Relative performance %** = (supplier score / benchmark) × 100, **except**:
  - *Case 1 — benchmark = 0 and supplier = 0*: relative % = **100%** (everyone
    tied at the best observed outcome — nobody is penalized for a shared zero).
  - *Case 2 — benchmark = 0 and supplier > 0*: mathematically unreachable if the
    benchmark is computed as `max(valid scores)`, since a positive score would
    itself have become the benchmark. Kept as a defensive guard: relative % = 0%,
    `warning = "Invalid benchmark state"`, surfaced if it ever fires (data bug).
  - *Case 3 — no supplier has a valid score for this criterion at all*: **not** the
    same as a zero benchmark. Status = `no_valid_scores`; the criterion is
    **excluded from PPI for this run only**, and the remaining active criteria's
    weights are **renormalized** to fill the gap (e.g. if a 20%-weight criterion is
    excluded, the other 80% of weight is scaled up to 100%). A clear warning names
    which criterion was excluded. This keeps no supplier being penalized for a
    shared data problem, while a real benchmark-zero (case 1) still means what it
    should.
- **Peer Performance Index (PPI)** = weighted average of criterion relative-performance
  percentages, using the (possibly renormalized, per case 3) weights.
  NexaWorks demo run: PPI = **94.4445**.

## Mandatory tie-break order

1. Higher PPI  2. Earlier submission date  3. Higher historical experience rating
4. Supplier name, ascending.

**PPI is rounded to 4 decimal places before comparison.** Without this, two
suppliers computed as `87.49999999` and `87.50000001` would never register as
"tied," rules 2–4 would silently never fire, and the sort order would depend on
floating-point noise rather than the business rule — this is covered by
`tests/test_ranking_tool.py::test_tie_break_float_noise_still_ties`.

This cascade is also exercised live, not just in unit tests: Keystone Digital,
Atlas Networks, and Solstice Technologies (in the synthetic data set below) are
given identical canned scores so they tie exactly on PPI. Keystone and Atlas
also share a submission date, forcing the tie all the way down to rule 3
(experience rating); Solstice's later date loses the tie on rule 2 alone. Load
the synthetic demo batch and check the Leaderboard tab's tie-break reason text
for all three to see every non-trivial rule fire on a real run.

## Incumbency & Transition Cost (deterministic criterion)

The brief's five criteria evaluate every proposal as a standing start. Real
procurement isn't symmetric: an incumbent carries a switching-cost advantage the
buyer avoids by not migrating — and a *poor* incumbent carries the opposite, since
the buyer pays that transition cost eventually anyway, on top of current bad
delivery. This is deliberately **not** LLM-scored — it is business policy, computed
by `ranking_tool.score_incumbency()`:

| Situation | Score (of 10) | Rationale |
|---|---|---|
| Non-incumbent | 5 | Baseline — normal transition cost assumed |
| Incumbent, performance ≥ 4/5 | 10 | Transition cost avoided, delivery good |
| Incumbent, performance = 3/5 | 7 | Transition cost avoided, delivery adequate |
| Incumbent, performance ≤ 2/5 | 2 | Transition cost paid eventually anyway, on top of poor delivery now |

Non-incumbents sit at the midpoint deliberately — a challenger isn't structurally
crushed, and a failing incumbent scores *below* a fresh entrant. It plugs into the
exact same weighted-score/benchmark/PPI pipeline as every LLM-scored criterion —
same formulas, same benchmarking, same tie-break — proving criteria don't need to
come from the LLM to be first-class.

## Evidence model — two independent signals, never conflated

- **`evidence_status`** (`missing` / `weak` / `moderate` / `strong`): the **LLM's own
  subjective judgment** of how well-supported a criterion is in the proposal.
- **`evidence_verified`** (boolean, per quote): **Python's objective fact-check** —
  does the claimed quote actually appear (fuzzy-matched, to tolerate PDF
  whitespace/hyphenation artifacts, via `difflib`) in that supplier's own
  extracted, page-mapped text? An unverified quote is flagged as a possible
  hallucination and never silently trusted.

These answer different questions ("is the proposal detailed?" vs. "did the model
make this up?") and are computed by different actors — collapsing them into one
field would hide exactly the failure mode this project is testing for. The demo
run deliberately includes one real example: Orbit Digital's canned response claims
*"We are SOC 2 Type II certified with continuous monitoring..."* — a quote that
does not appear in the actual document (which says Type II is only *scheduled*) —
and the Validation Tool catches it live, not just in a unit test.

## Prompt-injection defense (Vantage Cloud Solutions — adversarial test document)

The fifth synthetic proposal embeds, inside its Security & Compliance section, an
instruction telling any AI reader to ignore the scoring rubric and award maximum
marks. Two independent layers defend against it: (1) the system prompt frames all
proposal text as untrusted data and instructs the model to flag rather than obey
embedded directives, and (2) even if a score were inflated, every evidence quote
is independently checked against the source text regardless of what the model
claims. In both demo mode and live testing, Vantage is correctly flagged and
ranks last.

## LLM failure handling

One automatic retry, then the failure is recorded and surfaced with a manual
**Retry** button — no silent infinite retries. Critically, **a failure never
stops the batch and never silently produces a ranking that's missing a
supplier**: every supplier is still evaluated regardless of another
supplier's outcome, successful evaluations are cached, and the run status
becomes `INCOMPLETE` if even one supplier has failed. Ranking is only ever
computed once **every** supplier has succeeded — there is no override to force
a partial ranking. A failed supplier is unblocked by retrying it (or by
starting a new run without it); see `orchestrator.finalize_ranking()` and
`orchestrator.all_suppliers_resolved()`.

## Weight validation

If active criteria weights don't sum to 100%, the Ranking Tool auto-normalizes
proportionally and returns a warning describing exactly what changed (never a
silent adjustment) — the run proceeds rather than blocking. See
`tools/ranking_tool.normalize_weights()`.

## Demo mode — why an "offline" mode exists in a project about LLM evaluation

Streamlit Community Cloud deployments and graded demos share one risk: an
API outage, rate limit, or missing key on the reviewer's side shouldn't make the
whole submission undemonstrable. `tools/demo_provider.py` returns fixed,
hand-authored, realistic evaluation JSON for the eight synthetic suppliers — same
schema a real model returns, run through the identical Validation and Ranking
pipeline. It is what lets this README show a real leaderboard, a real caught
hallucination, a real resisted injection attempt, and a real multi-level
tie-break resolution, with zero dependency on model or network availability at
grading time. Untick it to use a live model.

## Synthetic test data (`data/synthetic/`)

One buyer RFP (a fictional enterprise procuring an AI-assisted IT service desk
platform) plus eight supplier responses, each with a deliberately distinct profile:

| Supplier | Profile |
|---|---|
| Apex Systems | Strong technical/security design; higher price; timeline exceeds the RFP's stated window |
| BrightPath Tech | Lowest price, fastest timeline; weak/no security certification; limited scale experience |
| NexaWorks | Balanced; strongest implementation plan; best support model and SLA regime |
| Orbit Digital | **Incumbent**; strong relationship/references; vague technical detail; mixed recent SLA record |
| Vantage Cloud Solutions | Adversarial test document — thin content plus an embedded prompt-injection attempt |
| Keystone Digital | **Tie-break test.** Identical canned score to Atlas Networks & Solstice Technologies -> ties on PPI; earliest submission date of the three -> wins |
| Atlas Networks | **Tie-break test.** Same PPI and same submission date as Keystone -> loses only on lower experience rating (rule 3) |
| Solstice Technologies | **Tie-break test.** Same PPI as Keystone/Atlas but a later submission date -> loses on rule 2 |

Regenerate with `python3 data/synthetic/render_pdfs.py`. Suggested per-supplier
metadata (submission date, experience rating, incumbency) for manual testing is
documented at the top of `data/synthetic/content.py` and pre-filled automatically
by the "Load synthetic demo batch" button in the app.

## Assumptions & decisions log

Every non-obvious call the brief left open, and what we chose:

1. Historical experience rating: **1–10** scale, tie-break input only — never enters
   the weighted score (would double-count against "Support & Experience").
2. Incumbent performance rating: **1–5** scale, drives the deterministic Incumbency
   criterion only.
3. Criteria are snapshotted **once, at batch creation** — not re-read mid-run.
4. A single failed supplier does **not** sink the whole batch, but also never
   silently produces a partial-looking-complete ranking (see "LLM failure handling").
5. `no_valid_scores` for a criterion excludes it from PPI with weight
   renormalization, rather than assigning a punitive 0% or blocking the run.
6. API keys are BYOK, session-memory only, never persisted to SQLite or disk.
7. PDFs must be text-based; scanned/image-only PDFs are explicitly rejected with a
   clear message rather than silently sending empty text to the LLM (OCR is out of
   scope for this project).

## Known limitations (stated, not hidden)

- **SQLite on Streamlit Community Cloud is ephemeral** — the container's
  filesystem resets on redeploy/reboot. `db/seed.py` re-seeds criteria
  automatically on startup if missing, but historical run rows will not survive a
  redeploy. For a graded demo this is fine (a fresh run takes seconds); it is not
  production persistence.
- Provider abstraction currently implements **Anthropic and OpenAI** directly over
  HTTP (matching this developer's stated preference for direct API integration
  over managed SDKs); adding a third provider is one class in `llm_providers.py`.
- Evidence verification uses fuzzy text matching, not exact PDF-coordinate
  bounding boxes — sufficient to catch fabricated claims, not a legal-grade
  citation system.

## Testing

```
pytest -q
```
15 tests covering: weight normalization, the full incumbency rule table, the
zero-benchmark 3-case logic, PPI exclusion/renormalization, deterministic
tie-break ordering (including the float-noise edge case), and two end-to-end
orchestrator tests (full successful pipeline with repeat-run determinism, and the
failure-gating path) using a stubbed provider — no network access required to run
the suite.

## Folder structure

```
app.py                  Streamlit UI — presentation only, no business logic
orchestrator.py          Agentic control plane (the DAG)
tools/
  document_tool.py        PDF -> page-mapped text
  evaluation_agent.py      Prompt construction + LLM call + JSON parsing
  llm_providers.py         Anthropic / OpenAI HTTP clients, common interface
  demo_provider.py         Offline canned-response provider (same interface)
  validation_tool.py       Schema, fill/clip, evidence verification
  ranking_tool.py          ALL deterministic math — score, benchmark, PPI, rank
db/
  schema.sql, seed.py, repository.py
data/synthetic/           Buyer RFP + 8 supplier PDFs + authoring source (content.py)
scripts/demo_run.py       Runs the full pipeline outside Streamlit (no browser needed)
tests/                    pytest suite (15 tests)
requirements.txt
```
