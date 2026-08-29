"""
Tests for the Validation Tool's defensive programming -- the firewall between
"whatever the LLM returned" and the Ranking Tool. These specifically cover
the hardening added after the code review: malformed/non-dict LLM output must
never crash the pipeline, duplicate criterion ids must not be silently
overwritten, the evidence match threshold must actually catch a misquote, and
a high score with no supporting evidence must be flagged.

Run with: pytest -q tests/test_validation_tool.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.validation_tool import validate_supplier_result, verify_evidence, EVIDENCE_MATCH_THRESHOLD


LLM_CRITERIA = [
    {"criterion_id": 1, "name": "Technical Capability", "weight": 50, "max_score": 10},
    {"criterion_id": 2, "name": "Security & Compliance", "weight": 50, "max_score": 10},
]

PAGES = [{"page": 1, "text": "Apex proposes a microservices-based platform with a dedicated triage engine."}]


def _good_result():
    return {
        "criteria": [
            {"criterion_id": 1, "score": 8, "evidence_status": "strong",
             "justification": "Solid.", "evidence": []},
            {"criterion_id": 2, "score": 6, "evidence_status": "moderate",
             "justification": "OK.", "evidence": []},
        ]
    }


def test_non_dict_llm_result_does_not_crash():
    results, warnings = validate_supplier_result("not a dict", LLM_CRITERIA, PAGES)
    assert len(results) == 2  # both criteria filled with the "missing" default
    assert all(r.score == 0 for r in results)
    assert any("was not a JSON object" in w for w in warnings)


def test_none_llm_result_does_not_crash():
    results, warnings = validate_supplier_result(None, LLM_CRITERIA, PAGES)
    assert len(results) == 2
    assert any("was not a JSON object" in w for w in warnings)


def test_non_dict_criteria_item_is_skipped_not_crashed():
    raw = {"criteria": [123, "oops", {"criterion_id": 1, "score": 7, "evidence_status": "weak",
                                       "justification": "x", "evidence": []}]}
    results, warnings = validate_supplier_result(raw, LLM_CRITERIA, PAGES)
    assert any("non-object criteria entry" in w for w in warnings)
    crit_1 = next(r for r in results if r.criterion_id == 1)
    assert crit_1.score == 7


def test_duplicate_criterion_id_keeps_first_and_warns():
    raw = {"criteria": [
        {"criterion_id": 1, "score": 9, "evidence_status": "strong", "justification": "first", "evidence": []},
        {"criterion_id": 1, "score": 2, "evidence_status": "weak", "justification": "duplicate", "evidence": []},
        {"criterion_id": 2, "score": 5, "evidence_status": "moderate", "justification": "ok", "evidence": []},
    ]}
    results, warnings = validate_supplier_result(raw, LLM_CRITERIA, PAGES)
    crit_1 = next(r for r in results if r.criterion_id == 1)
    assert crit_1.score == 9  # first one wins
    assert crit_1.justification == "first"
    assert any("more than one result for criterion_id=1" in w for w in warnings)


def test_high_score_with_no_evidence_is_flagged():
    raw = {"criteria": [
        {"criterion_id": 1, "score": 9, "evidence_status": "missing", "justification": "trust me", "evidence": []},
        {"criterion_id": 2, "score": 5, "evidence_status": "moderate", "justification": "ok", "evidence": []},
    ]}
    results, warnings = validate_supplier_result(raw, LLM_CRITERIA, PAGES)
    assert any("above half-marks but no supporting evidence" in w for w in warnings)


def test_low_score_with_no_evidence_is_not_flagged():
    raw = {"criteria": [
        {"criterion_id": 1, "score": 2, "evidence_status": "missing", "justification": "not addressed", "evidence": []},
        {"criterion_id": 2, "score": 5, "evidence_status": "moderate", "justification": "ok", "evidence": []},
    ]}
    _, warnings = validate_supplier_result(raw, LLM_CRITERIA, PAGES)
    assert not any("above half-marks" in w for w in warnings)


def test_evidence_verification_catches_a_meaning_flipping_misquote():
    # Genuine text says the platform HAS a triage engine; a one-word-flip
    # misquote claims the opposite. At the old 0.82 threshold this could pass
    # as "verified" by character overlap alone -- at 0.95 it must not.
    misquote = [{"quote": "Apex proposes a microservices-based platform with NO triage engine", "page": 1}]
    verified = verify_evidence(misquote, PAGES)
    assert verified[0]["verified"] is False


def test_evidence_verification_still_passes_exact_quote():
    exact = [{"quote": "Apex proposes a microservices-based platform with a dedicated triage engine", "page": 1}]
    verified = verify_evidence(exact, PAGES)
    assert verified[0]["verified"] is True
    assert verified[0]["verified_page"] == 1
    assert verified[0]["claimed_page"] == 1


def test_evidence_verification_tracks_claimed_vs_verified_page_on_off_by_one():
    off_by_one = [{"quote": "Apex proposes a microservices-based platform with a dedicated triage engine", "page": 2}]
    verified = verify_evidence(off_by_one, PAGES)
    assert verified[0]["verified"] is True
    assert verified[0]["claimed_page"] == 2   # what the LLM claimed
    assert verified[0]["verified_page"] == 1  # where it was actually found
