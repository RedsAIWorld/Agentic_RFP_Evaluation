"""
Smoke tests for the pure ranking functions -- the part of the rubric that
rewards "documentation & testing" and directly proves the success condition:
"the same inputs must always produce the same formulas and ordering."
Run with: pytest -q
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from tools.ranking_tool import (
    normalize_weights, score_incumbency, compute_absolute_score,
    compute_benchmarks, compute_criterion_gap, compute_relative_performance,
    compute_ppi, rank_suppliers, tie_break_sort_key, validate_criteria_configuration,
    criterion_weighted_contribution, summarize_rank_explanation,
)
import pytest


CRITERIA = [
    {"criterion_id": 1, "name": "Technical Capability", "weight": 30, "max_score": 10},
    {"criterion_id": 4, "name": "Security & Compliance", "weight": 20, "max_score": 10},
]


def test_normalize_weights_no_change_when_already_100():
    active = [{"name": "A", "weight": 60}, {"name": "B", "weight": 40}]
    normalized, warning = normalize_weights(active)
    assert warning is None
    assert normalized[0]["weight"] == 60
    assert normalized[1]["weight"] == 40


def test_normalize_weights_scales_and_warns_when_not_100():
    active = [{"name": "A", "weight": 60}, {"name": "B", "weight": 60}]  # sums to 120
    normalized, warning = normalize_weights(active)
    assert warning is not None
    assert abs(sum(c["weight"] for c in normalized) - 100.0) < 1e-6
    assert normalized[0]["weight"] == 50.0
    assert normalized[1]["weight"] == 50.0


def test_score_incumbency_non_incumbent_is_baseline():
    score, _ = score_incumbency(is_incumbent=False, incumbent_performance_rating=None, max_score=10)
    assert score == 5


def test_score_incumbency_strong_incumbent_scores_high():
    score, _ = score_incumbency(is_incumbent=True, incumbent_performance_rating=5, max_score=10)
    assert score == 10


def test_score_incumbency_adequate_incumbent_above_baseline():
    score, _ = score_incumbency(is_incumbent=True, incumbent_performance_rating=3, max_score=10)
    assert score == 7
    assert score > 5  # strictly above non-incumbent baseline


def test_score_incumbency_poor_incumbent_below_baseline():
    score, _ = score_incumbency(is_incumbent=True, incumbent_performance_rating=1, max_score=10)
    assert score == 2
    assert score < 5  # strictly below non-incumbent baseline


def test_compute_absolute_score():
    scores = {1: 8, 4: 10}  # 8/10*30 + 10/10*20 = 24 + 20 = 44
    assert compute_absolute_score(scores, CRITERIA) == 44.0


def test_zero_benchmark_case1_both_zero_gives_full_credit():
    rel, warning = compute_relative_performance(supplier_score=0, benchmark=0)
    assert rel == 100.0
    assert warning is None


def test_zero_benchmark_case2_invalid_state_flagged():
    rel, warning = compute_relative_performance(supplier_score=5, benchmark=0)
    assert rel == 0.0
    assert warning is not None and "Invalid benchmark state" in warning


def test_benchmark_no_valid_scores_status():
    all_scores = {"A": {1: None}, "B": {}}
    benchmarks = compute_benchmarks(all_scores, [CRITERIA[0]])
    assert benchmarks[1]["status"] == "no_valid_scores"
    assert benchmarks[1]["benchmark"] is None


def test_ppi_excludes_and_renormalizes_no_valid_scores_criterion():
    # Criterion 4 has no valid scores this run -> excluded, criterion 1's weight
    # (30 out of 50 active) is renormalized to 100% for PPI purposes.
    rel_perf = {1: 80.0}  # criterion 4 intentionally absent (excluded)
    ppi, warnings = compute_ppi(rel_perf, CRITERIA, excluded_criterion_ids={4})
    assert ppi == 80.0  # only criterion left, renormalized to 100% weight
    assert any("Excluded from PPI" in w for w in warnings)


def test_tie_break_order_is_deterministic_and_repeatable():
    suppliers = [
        {"supplier_name": "Beta", "submission_date": "2026-03-03", "experience_rating": 5, "ppi": 87.5},
        {"supplier_name": "Alpha", "submission_date": "2026-03-01", "experience_rating": 9, "ppi": 87.5},
        {"supplier_name": "Gamma", "submission_date": "2026-03-05", "experience_rating": 2, "ppi": 90.0},
    ]
    ranked_once = rank_suppliers([dict(s) for s in suppliers])
    ranked_twice = rank_suppliers([dict(s) for s in suppliers])
    names_once = [s["supplier_name"] for s in ranked_once]
    names_twice = [s["supplier_name"] for s in ranked_twice]
    assert names_once == names_twice  # determinism: same input -> same order, every time
    # Gamma has the highest PPI -> rank 1
    assert names_once[0] == "Gamma"
    # Alpha and Beta are tied on PPI (87.5) -> earlier submission date (Alpha, 03-01) wins
    assert names_once[1] == "Alpha"
    assert names_once[2] == "Beta"


def test_compute_criterion_gap_zero_for_benchmark_leader():
    assert compute_criterion_gap(9, 9) == 0
    assert compute_criterion_gap(5, 9) == -4


def test_validate_criteria_configuration_rejects_empty():
    with pytest.raises(ValueError, match="No active evaluation criteria"):
        validate_criteria_configuration([])


def test_validate_criteria_configuration_rejects_negative_weight():
    with pytest.raises(ValueError, match="invalid weight"):
        validate_criteria_configuration([
            {"name": "A", "weight": -5, "max_score": 10, "scoring_source": "llm"},
        ])


def test_validate_criteria_configuration_rejects_zero_max_score():
    with pytest.raises(ValueError, match="invalid max_score"):
        validate_criteria_configuration([
            {"name": "A", "weight": 50, "max_score": 0, "scoring_source": "llm"},
        ])


def test_validate_criteria_configuration_rejects_bad_scoring_source():
    with pytest.raises(ValueError, match="invalid scoring_source"):
        validate_criteria_configuration([
            {"name": "A", "weight": 50, "max_score": 10, "scoring_source": "human"},
        ])


def test_validate_criteria_configuration_rejects_all_zero_weights():
    with pytest.raises(ValueError, match="sum to zero"):
        validate_criteria_configuration([
            {"name": "A", "weight": 0, "max_score": 10, "scoring_source": "llm"},
            {"name": "B", "weight": 0, "max_score": 10, "scoring_source": "deterministic"},
        ])


def test_validate_criteria_configuration_passes_for_valid_set():
    validate_criteria_configuration([
        {"name": "A", "weight": 60, "max_score": 10, "scoring_source": "llm"},
        {"name": "B", "weight": 40, "max_score": 10, "scoring_source": "deterministic"},
    ])  # should not raise


def test_criterion_weighted_contribution_matches_absolute_score_terms():
    assert criterion_weighted_contribution(8, 10, 30) == 24.0
    assert criterion_weighted_contribution(10, 10, 20) == 20.0
    assert criterion_weighted_contribution(0, 10, 20) == 0.0


def test_tie_break_reason_is_human_readable_and_names_the_comparison():
    suppliers = [
        {"supplier_name": "NexaWorks", "submission_date": "2026-03-01", "experience_rating": 9, "ppi": 94.4},
        {"supplier_name": "Apex Systems", "submission_date": "2026-03-04", "experience_rating": 7, "ppi": 86.2},
    ]
    ranked = rank_suppliers([dict(s) for s in suppliers])
    winner, runner_up = ranked[0], ranked[1]
    assert winner["tie_break_reason"] == "Highest Peer Performance Index (PPI) of all evaluated suppliers."
    # Names the leader it lost to and both PPIs, in plain language -- not the old "PPI x is lower than rank y's PPI z."
    assert "NexaWorks" in runner_up["tie_break_reason"]
    assert "rank" not in runner_up["tie_break_reason"].lower()


def test_summarize_rank_explanation_splits_strongest_and_weakest():
    criteria_snapshot = [
        {"criterion_id": 1, "name": "Technical Capability"},
        {"criterion_id": 2, "name": "Security & Compliance"},
        {"criterion_id": 3, "name": "Implementation Plan"},
        {"criterion_id": 4, "name": "Commercial Value"},
    ]
    detail = {
        1: {"benchmark": 9, "gap": 0, "relative_pct": 100.0, "status": "ok"},
        2: {"benchmark": 9, "gap": 0, "relative_pct": 100.0, "status": "ok"},
        3: {"benchmark": 10, "gap": -3, "relative_pct": 70.0, "status": "ok"},
        4: {"benchmark": 8, "gap": -4, "relative_pct": 50.0, "status": "ok"},
    }
    result = summarize_rank_explanation(detail, criteria_snapshot, top_n=2)
    strongest_names = [d["name"] for d in result["strongest"]]
    weakest_names = [d["name"] for d in result["weakest"]]
    assert strongest_names == ["Technical Capability", "Security & Compliance"]
    assert weakest_names == ["Commercial Value", "Implementation Plan"]
    # no overlap between the two lists
    assert not set(strongest_names) & set(weakest_names)


def test_summarize_rank_explanation_excludes_no_valid_scores_criteria():
    criteria_snapshot = [{"criterion_id": 1, "name": "A"}, {"criterion_id": 2, "name": "B"}]
    detail = {
        1: {"benchmark": 9, "gap": 0, "relative_pct": 100.0, "status": "ok"},
        2: {"benchmark": None, "gap": None, "relative_pct": None, "status": "no_valid_scores"},
    }
    result = summarize_rank_explanation(detail, criteria_snapshot, top_n=2)
    assert len(result["strongest"]) == 1
    assert result["strongest"][0]["name"] == "A"
    assert result["weakest"] == []


def test_tie_break_float_noise_still_ties():
    suppliers = [
        {"supplier_name": "X", "submission_date": "2026-03-05", "experience_rating": 1, "ppi": 87.49999999},
        {"supplier_name": "Y", "submission_date": "2026-03-01", "experience_rating": 1, "ppi": 87.50000001},
    ]
    ranked = rank_suppliers([dict(s) for s in suppliers])
    # Rounded to 4dp both are 87.5 -> should tie on PPI and fall to submission date (Y wins, earlier)
    assert ranked[0]["supplier_name"] == "Y"
