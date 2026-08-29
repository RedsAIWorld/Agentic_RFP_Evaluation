# What to send at the start of a project like this

Paste something like this at the very start of the conversation, before any building begins:

---

I'm building [project] for [deadline]. Before we write any code, let's lock four things:

1. **Environment**: I want to work in [one place — e.g. "this cloud session only" / "VS Code on my machine only"]. Don't assume a second session or machine is involved unless I say so.
2. **Git**: The repo is [URL]. Confirm up front whether you can push from here directly or whether pushes have to happen from my machine, so we don't discover it mid-deadline.
3. **Visual bar**: This needs to look like [a real product / a polished demo / a quick internal tool] — not default Streamlit/Bootstrap/whatever the framework ships with. Pick the styling approach before writing the first screen, not after I see it and reject it.
4. **Speed vs. hardening trade-off**: given the deadline, build the happy path first and explicitly tell me what you're deferring (input validation, malformed-response handling, edge cases). We'll do one dedicated hardening pass after the deadline, not discover it as a surprise 26-item review.

---

## Why each of these existed as a gap this time

- No environment decision up front → ended up with two live Claude sessions (this cloud one + VS Code locally) touching the same project, which cost a full round trip to sort out ("help me do this in one terminal").
- No git-push-location check up front → discovered mid-project that this cloud sandbox can't push to GitHub, after already trying.
- No visual bar stated up front → built a functionally-complete but plain UI in the 6-hour sprint, which you then rejected, triggering a second full design pass instead of getting it right the first time.
- No explicit "we're deferring hardening" agreement → the fast build accumulated real but unsurprising debt (no input validation, a deprecated datetime call, dead code, silent duplicate-overwrite bugs), which then showed up as one large 26-point review that took a full pass just to triage before any fixing could start.

## What worked and is worth repeating

- Doing a "don't build yet" requirements/brief-review phase before touching code.
- Live-testing against the real API early rather than trusting only canned demo responses — this caught a genuine bug (evidence quotes split across a PDF page boundary).
- Weighing an externally-authored "decisions" doc against independent analysis instead of just complying with it.
- Reviewing the actual codebase file-by-file before agreeing a review's claims were accurate, rather than taking a review's framing at face value.

## What changed in this pass (for reference)

- Removed the partial-ranking override entirely — a run only produces a ranking once every supplier succeeds; failures no longer block others from being evaluated, they just block ranking until retried.
- Fixed the deprecated `datetime.utcnow()` call.
- Added supplier-name validation (non-empty, unique per batch) and a criteria-configuration validator (no active criteria / bad weights / bad max_score / bad scoring_source / zero total weight), both raised before any evaluation work starts.
- Benchmark, gap-vs-benchmark, and relative-performance are now computed AND persisted per criterion (previously computed transiently and discarded) — surfaced in the Detailed Scorecards tab.
- Validation Tool hardened against non-dict/malformed LLM JSON, duplicate criterion ids (now warned instead of silently overwritten), raised the evidence-match threshold from 0.82 to 0.95 (catches meaning-flipping misquotes), tracks claimed-page vs. verified-page separately, and flags a high score with no supporting evidence.
- `scripts/demo_run.py` path bug fixed so it runs as documented.
- System prompt now explicitly tells the model not to trust a supplier's self-declared "certified/approved/pre-qualified" claims without evidence.
- 19 new tests added (34 total, all passing) covering every fix above; full demo pipeline and a live Streamlit run were both re-verified end to end.
