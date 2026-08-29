"""
Validation Tool -- the firewall between "what the LLM said" and "what the
Ranking Tool is allowed to compute on".

Responsibilities (all deterministic Python, no LLM calls):
1. Schema check: every active LLM-scored criterion must have exactly one
   result; scores must be integers in range.
2. Normalize: fill missing criteria with a flagged default, clip out-of-range
   scores, coerce wrong types where safe.
3. Evidence verification: check every claimed quote actually appears
   (fuzzily -- PDF extraction mangles whitespace/hyphenation) in the
   supplier's own extracted, page-mapped text. Mark evidence_verified and
   raise a distinct warning for anything that looks hallucinated -- this is
   independent of evidence_status (the LLM's own subjective quality
   judgment, e.g. "missing" vs "strong"). Both fields are kept: one is the
   model's opinion, the other is Python's fact-check.
4. Record every correction/anomaly as a structured warning -- nothing is
   silently changed.
"""
from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re


EVIDENCE_MATCH_THRESHOLD = 0.95  # fuzzy-match ratio; below this, flag as unverifiable.
# Raised from 0.82: a short quote can flip meaning on a small edit (e.g. "ARE certified"
# vs "are NOT certified" is still ~0.9 similar by character overlap), so the bar needs to
# be close to exact to actually catch a misquote rather than just catch typos.
VALID_EVIDENCE_STATUSES = {"missing", "weak", "moderate", "strong"}


@dataclass
class ValidatedCriterionResult:
    criterion_id: int
    name: str
    weight: float
    max_score: int
    score: int
    justification: str
    evidence_status: str
    evidence: list           # list of {"quote":..., "page":..., "verified": bool}
    evidence_verified: bool  # True only if at least one evidence item verified (or none claimed & status=missing)
    warnings: list = field(default_factory=list)


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def _quote_found_in_page(quote: str, page_text: str) -> bool:
    """Exact normalized substring match first (cheap, precise), fuzzy fallback."""
    nq, npage = _normalize_text(quote), _normalize_text(page_text)
    if not nq:
        return False
    if nq in npage:
        return True
    # Fuzzy fallback: slide the quote length window is expensive; instead compare
    # the quote against the whole page text with SequenceMatcher quick_ratio,
    # good enough at this text scale (a few KB per page).
    ratio = SequenceMatcher(None, nq, npage).quick_ratio()
    if ratio >= EVIDENCE_MATCH_THRESHOLD:
        return True
    # Also try: is the quote a fuzzy-close substring of some window of similar length?
    window = len(nq)
    if window == 0 or len(npage) <= window:
        return ratio >= EVIDENCE_MATCH_THRESHOLD
    step = max(1, window // 2)
    for start in range(0, len(npage) - window + 1, step):
        chunk = npage[start:start + window + step]
        if SequenceMatcher(None, nq, chunk).ratio() >= EVIDENCE_MATCH_THRESHOLD:
            return True
    return False


def verify_evidence(evidence_items: list, pages: list) -> list:
    """
    pages: list of {"page": int, "text": str} from document_tool.
    Returns evidence items annotated with "verified": bool.
    """
    pages_by_num = {p["page"]: p["text"] for p in pages}
    verified_items = []
    for item in evidence_items or []:
        quote = item.get("quote", "")
        page_num = item.get("page")
        page_text = pages_by_num.get(page_num, "")
        # If the claimed page doesn't exist or is empty, also check neighbouring
        # pages in case the model was off by one (common, harmless LLM slip).
        verified = _quote_found_in_page(quote, page_text)
        verified_page = page_num if verified else None
        if not verified:
            for alt_page in (page_num - 1, page_num + 1):
                if alt_page in pages_by_num and _quote_found_in_page(quote, pages_by_num[alt_page]):
                    verified = True
                    verified_page = alt_page
                    break
        if not verified:
            # A sentence can straddle a physical page break in the source PDF (the
            # text before the break lands on page N, the rest on page N+1), so a
            # verbatim quote can be split across two pages even though it's real.
            # Join adjacent pages and re-check before concluding it's unverifiable.
            for a, b in ((page_num, page_num + 1), (page_num - 1, page_num)):
                if a in pages_by_num and b in pages_by_num:
                    joined = pages_by_num[a] + " " + pages_by_num[b]
                    if _quote_found_in_page(quote, joined):
                        verified = True
                        verified_page = f"{a}-{b}"
                        break
        verified_items.append({
            "quote": quote, "page": page_num, "claimed_page": page_num,
            "verified_page": verified_page, "verified": verified,
        })
    return verified_items


def validate_supplier_result(raw_llm_result: dict, llm_criteria: list, pages: list) -> tuple[list, list]:
    """
    Validates one supplier's raw LLM JSON against the active LLM-scored criteria.

    Returns (validated_results: list[ValidatedCriterionResult], run_warnings: list[str])
    """
    warnings = []
    criteria_by_id = {c["criterion_id"]: c for c in llm_criteria}
    raw_by_id = {}

    if not isinstance(raw_llm_result, dict):
        warnings.append(
            f"LLM response was not a JSON object (got {type(raw_llm_result).__name__}) -- treated as empty."
        )
        raw_llm_result = {}

    raw_criteria = raw_llm_result.get("criteria", [])
    if not isinstance(raw_criteria, list):
        warnings.append("LLM response 'criteria' was not a list -- treated as empty.")
        raw_criteria = []

    for item in raw_criteria:
        if not isinstance(item, dict):
            warnings.append(f"LLM returned a non-object criteria entry ({item!r}) -- ignored.")
            continue
        cid = item.get("criterion_id")
        if cid not in criteria_by_id:
            warnings.append(f"LLM returned a result for unknown criterion_id={cid} -- ignored.")
            continue
        if cid in raw_by_id:
            warnings.append(
                f"LLM returned more than one result for criterion_id={cid} -- "
                f"keeping the first, discarding the duplicate."
            )
            continue
        raw_by_id[cid] = item

    results = []
    for criterion in llm_criteria:
        cid = criterion["criterion_id"]
        name = criterion["name"]
        max_score = criterion["max_score"]
        raw = raw_by_id.get(cid)

        if raw is None:
            warnings.append(
                f"Missing result for criterion '{name}' (id={cid}) -- filled with score 0 "
                f"and evidence_status='missing'."
            )
            results.append(ValidatedCriterionResult(
                criterion_id=cid, name=name, weight=criterion["weight"], max_score=max_score,
                score=0, justification="No result returned by the LLM for this criterion.",
                evidence_status="missing", evidence=[], evidence_verified=False,
                warnings=[f"Missing LLM result, filled with 0."],
            ))
            continue

        # --- score: coerce + clip ---
        raw_score = raw.get("score", 0)
        try:
            score = int(round(float(raw_score)))
        except (TypeError, ValueError):
            warnings.append(f"Criterion '{name}': non-numeric score {raw_score!r} -- coerced to 0.")
            score = 0
        item_warnings = []
        if score < 0 or score > max_score:
            clipped = max(0, min(score, max_score))
            item_warnings.append(f"Score {score} out of range [0,{max_score}] -- clipped to {clipped}.")
            warnings.append(f"Criterion '{name}': score {score} out of range -- clipped to {clipped}.")
            score = clipped

        # --- evidence_status ---
        evidence_status = str(raw.get("evidence_status", "")).strip().lower()
        if evidence_status not in VALID_EVIDENCE_STATUSES:
            warnings.append(
                f"Criterion '{name}': invalid/missing evidence_status "
                f"{raw.get('evidence_status')!r} -- defaulted to 'weak'."
            )
            evidence_status = "weak"

        # --- justification ---
        justification = str(raw.get("justification", "")).strip() or "No justification provided."

        # --- evidence verification against the actual extracted source text ---
        raw_evidence = raw.get("evidence", [])
        if not isinstance(raw_evidence, list):
            raw_evidence = []
        verified_evidence = verify_evidence(raw_evidence, pages)
        any_claimed = len(verified_evidence) > 0
        any_verified = any(e["verified"] for e in verified_evidence)
        unverified = [e for e in verified_evidence if not e["verified"]]
        if unverified:
            for e in unverified:
                warnings.append(
                    f"Criterion '{name}': evidence quote could not be located in the source "
                    f"document (claimed page {e['page']}) -- possible hallucination: "
                    f"\"{e['quote'][:100]}...\""
                )
            item_warnings.append(f"{len(unverified)} evidence item(s) unverifiable against source text.")

        evidence_verified = any_verified if any_claimed else (evidence_status == "missing")

        if (not any_claimed or evidence_status == "missing") and score > max_score / 2:
            msg = (
                f"Criterion '{name}': score {score}/{max_score} is above half-marks but no "
                f"supporting evidence was cited -- treat this score with caution."
            )
            warnings.append(msg)
            item_warnings.append(msg)

        results.append(ValidatedCriterionResult(
            criterion_id=cid, name=name, weight=criterion["weight"], max_score=max_score,
            score=score, justification=justification, evidence_status=evidence_status,
            evidence=verified_evidence, evidence_verified=evidence_verified,
            warnings=item_warnings,
        ))

    return results, warnings
