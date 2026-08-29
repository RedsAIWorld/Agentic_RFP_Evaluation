"""
Ranking Tool -- 100% pure, deterministic Python. No LLM calls happen or are
allowed anywhere in this file. This is the module the brief means when it
says "the LLM may judge proposal content, but it must not decide the final
arithmetic, benchmark, tie-breaks, or rank."

Every function here is a pure function: same inputs -> same outputs, always.
That purity is what "the same inputs must always produce the same formulas
and ordering" (the brief's success condition) actually rests on.
"""
from dataclasses import dataclass, field


ZERO_BENCHMARK_FULL_CREDIT = 100.0  # Case 1: benchmark==0 and supplier==0 -> full credit
PPI_ROUND_DP = 4                    # tie-break comparisons happen on this rounded value


# ---------------------------------------------------------------------------
# Weight normalization (locked decision: warn + auto-normalize)
# ---------------------------------------------------------------------------

def normalize_weights(active_criteria: list) -> tuple[list, str | None]:
    """
    active_criteria: list of dicts with at least 'weight'.
    If weights don't sum to 100 (within floating tolerance), scale them
    proportionally so they do, and return a warning string describing exactly
    what was changed. Does not mutate the input list.
    """
    total = sum(c["weight"] for c in active_criteria)
    if abs(total - 100.0) < 1e-6:
        return [dict(c) for c in active_criteria], None

    if total <= 0:
        raise ValueError("Active criteria weights sum to zero or less -- cannot normalize.")

    factor = 100.0 / total
    normalized = []
    changes = []
    for c in active_criteria:
        new_weight = round(c["weight"] * factor, 4)
        if abs(new_weight - c["weight"]) > 1e-9:
            changes.append(f"{c['name']}: {c['weight']}% -> {new_weight}%")
        nc = dict(c)
        nc["weight"] = new_weight
        normalized.append(nc)

    warning = (
        f"Active criteria weights summed to {total}%, not 100% -- automatically "
        f"normalized proportionally. Changes: " + "; ".join(changes)
    )
    return normalized, warning


# ---------------------------------------------------------------------------
# Incumbency (deterministic criterion) -- score_incumbency
# ---------------------------------------------------------------------------

def score_incumbency(is_incumbent: bool, incumbent_performance_rating, max_score: int = 10) -> tuple[int, str]:
    """
    Rule table (locked decision, see workflow-and-tutoring-plan.md discussion):

      Non-incumbent                                  -> baseline, mid-scale
      Incumbent, performance >= 4/5, no issues        -> near max: transition cost avoided, good delivery
      Incumbent, performance == 3/5                   -> above baseline: transition cost avoided, adequate delivery
      Incumbent, performance <= 2/5                   -> below baseline: eventual transition cost + poor delivery now

    Scaled onto max_score (default 10) so it composes with any max_score
    the criteria table is configured with.
    """
    def scale(x_out_of_10):
        return round(x_out_of_10 / 10.0 * max_score)

    if not is_incumbent:
        return scale(5), "Non-incumbent: baseline transition-cost assumption applied."

    if incumbent_performance_rating is None:
        return scale(5), "Marked incumbent but no performance rating supplied -- treated as baseline."

    if incumbent_performance_rating >= 4:
        return scale(10), (
            f"Incumbent with strong performance ({incumbent_performance_rating}/5): "
            f"transition cost avoided and delivery has been good."
        )
    elif incumbent_performance_rating == 3:
        return scale(7), (
            f"Incumbent with adequate performance ({incumbent_performance_rating}/5): "
            f"transition cost avoided, delivery adequate."
        )
    else:
        return scale(2), (
            f"Incumbent with weak performance ({incumbent_performance_rating}/5): "
            f"transition cost will eventually be paid anyway, on top of current poor delivery."
        )


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

@dataclass
class SupplierScoreInputs:
    supplier_name: str
    submission_date: str          # ISO 'YYYY-MM-DD'
    experience_rating: int        # 1-10, TIE-BREAK ONLY, never enters the score
    criterion_scores: dict        # {criterion_id: score (0..max_score)}


def compute_absolute_score(criterion_scores: dict, criteria: list) -> float:
    """Sum of (criterion_score / max_score) * weight, across the given criteria list."""
    total = 0.0
    for c in criteria:
        cid = c["criterion_id"]
        score = criterion_scores.get(cid, 0)
        total += (score / c["max_score"]) * c["weight"]
    return round(total, 4)


def compute_benchmarks(all_supplier_criterion_scores: dict, criteria: list) -> dict:
    """
    all_supplier_criterion_scores: {supplier_name: {criterion_id: score}}
    Returns {criterion_id: {"benchmark": float|None, "status": "ok"|"no_valid_scores"}}

    A score counts as "valid" if it is a number >= 0. (Validation already
    clipped to [0, max_score], so every score reaching here is already valid
    by construction -- "no_valid_scores" covers the case where a supplier's
    evaluation failed entirely and contributed no score at all for this run.)
    """
    benchmarks = {}
    for c in criteria:
        cid = c["criterion_id"]
        valid_scores = [
            scores[cid] for scores in all_supplier_criterion_scores.values()
            if cid in scores and scores[cid] is not None
        ]
        if not valid_scores:
            benchmarks[cid] = {"benchmark": None, "status": "no_valid_scores"}
        else:
            benchmarks[cid] = {"benchmark": max(valid_scores), "status": "ok"}
    return benchmarks


def compute_criterion_gap(supplier_score: float, benchmark: float) -> float:
    """Supplier score - benchmark. Zero for the benchmark leader, negative otherwise."""
    return round(supplier_score - benchmark, 4)


def compute_relative_performance(supplier_score: float, benchmark: float) -> tuple[float, str | None]:
    """
    Locked zero-benchmark rule (three cases):
      Case 1: benchmark == 0 and supplier == 0        -> 100% (same as everyone else)
      Case 2: benchmark == 0 and supplier > 0          -> mathematically unreachable if benchmark is
                                                            computed as max(valid scores); defensive guard,
                                                            flags "Invalid benchmark state" if it ever occurs
      Case 3 (no_valid_scores) is handled by the caller (compute_ppi), not here --
              this function assumes a numeric benchmark from an "ok" status.
    Returns (relative_percentage, warning_or_None)
    """
    if benchmark == 0:
        if supplier_score == 0:
            return ZERO_BENCHMARK_FULL_CREDIT, None
        else:
            return 0.0, "Invalid benchmark state: benchmark is 0 but a supplier score is > 0."
    return round((supplier_score / benchmark) * 100.0, 4), None


def compute_ppi(criterion_relative_performances: dict, criteria: list, excluded_criterion_ids: set) -> tuple[float, list]:
    """
    criterion_relative_performances: {criterion_id: relative_percentage}  (only for included criteria)
    criteria: the full active criteria list (weights already normalized to sum to 100 over the FULL set)
    excluded_criterion_ids: criteria with status "no_valid_scores" this run -- excluded from PPI,
                            with the remaining weights renormalized (locked decision).

    Returns (ppi, warnings)
    """
    warnings = []
    included = [c for c in criteria if c["criterion_id"] not in excluded_criterion_ids]
    if excluded_criterion_ids:
        excluded_names = [c["name"] for c in criteria if c["criterion_id"] in excluded_criterion_ids]
        warnings.append(
            f"Excluded from PPI (no supplier had a valid score this run): {', '.join(excluded_names)}. "
            f"Remaining criteria weights renormalized for PPI purposes."
        )
    included_weight_total = sum(c["weight"] for c in included)
    if included_weight_total <= 0:
        warnings.append("All criteria excluded (no valid scores anywhere) -- PPI cannot be computed, set to 0.")
        return 0.0, warnings

    ppi = 0.0
    for c in included:
        cid = c["criterion_id"]
        rel = criterion_relative_performances.get(cid, 0.0)
        renormalized_weight = c["weight"] / included_weight_total * 100.0
        ppi += rel * (renormalized_weight / 100.0)

    return round(ppi, PPI_ROUND_DP), warnings


# ---------------------------------------------------------------------------
# Tie-break + ranking
# ---------------------------------------------------------------------------

def tie_break_sort_key(supplier: dict):
    """
    Mandatory order (brief): 1) higher PPI, 2) earlier submission date,
    3) higher historical experience rating, 4) supplier name ascending.
    PPI is rounded before comparison so floating-point noise can never
    prevent a "tie" that should trigger rules 2-4.
    """
    ppi_rounded = round(supplier["ppi"], PPI_ROUND_DP)
    return (
        -ppi_rounded,                       # higher PPI first
        supplier["submission_date"],        # earlier date first (ISO strings sort correctly)
        -supplier["experience_rating"],     # higher experience first
        supplier["supplier_name"],          # A-Z
    )


def rank_suppliers(suppliers: list) -> list:
    """
    suppliers: list of dicts with keys: supplier_name, submission_date,
               experience_rating, ppi
    Returns the same list, sorted and with 'final_rank' and
    'tie_break_reason' assigned. Stable sort guarantees determinism.
    """
    ordered = sorted(suppliers, key=tie_break_sort_key)
    for i, s in enumerate(ordered):
        s["final_rank"] = i + 1
        if i == 0:
            s["tie_break_reason"] = "Highest PPI."
        else:
            prev = ordered[i - 1]
            if round(prev["ppi"], PPI_ROUND_DP) != round(s["ppi"], PPI_ROUND_DP):
                s["tie_break_reason"] = (
                    f"PPI {s['ppi']:.4f} is lower than rank {i}'s PPI {prev['ppi']:.4f}."
                )
            elif prev["submission_date"] != s["submission_date"]:
                s["tie_break_reason"] = (
                    f"PPI tied with rank {i} at {s['ppi']:.4f} -> decided by submission date "
                    f"({prev['submission_date']} is earlier than {s['submission_date']})."
                )
            elif prev["experience_rating"] != s["experience_rating"]:
                s["tie_break_reason"] = (
                    f"PPI and submission date tied with rank {i} -> decided by historical experience "
                    f"rating ({prev['experience_rating']} vs {s['experience_rating']})."
                )
            else:
                s["tie_break_reason"] = (
                    f"PPI, submission date, and experience rating all tied with rank {i} -> "
                    f"decided alphabetically by supplier name."
                )
    return ordered
