"""
Thin data-access layer. No business logic lives here -- just reads/writes.
"""
import json
from .seed import get_connection


def get_active_criteria():
    """Returns active criteria ordered for display/prompting, as list of dicts."""
    conn = get_connection()
    rows = conn.execute(
        """SELECT criterion_id, name, description, weight, max_score,
                  scoring_source, is_active, sort_order
           FROM evaluation_criteria
           WHERE is_active = 1
           ORDER BY sort_order"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_criteria():
    conn = get_connection()
    rows = conn.execute(
        """SELECT criterion_id, name, description, weight, max_score,
                  scoring_source, is_active, sort_order
           FROM evaluation_criteria
           ORDER BY sort_order"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_criterion(criterion_id, weight=None, is_active=None):
    conn = get_connection()
    if weight is not None:
        conn.execute(
            "UPDATE evaluation_criteria SET weight = ? WHERE criterion_id = ?",
            (weight, criterion_id),
        )
    if is_active is not None:
        conn.execute(
            "UPDATE evaluation_criteria SET is_active = ? WHERE criterion_id = ?",
            (1 if is_active else 0, criterion_id),
        )
    conn.commit()
    conn.close()


def create_run(rfp_run_id, created_at, criteria_snapshot, provider, model, weight_warning=None):
    conn = get_connection()
    conn.execute(
        """INSERT INTO rfp_runs
           (rfp_run_id, created_at, status, criteria_snapshot_json, provider, model, weight_warning)
           VALUES (?, ?, 'IN_PROGRESS', ?, ?, ?, ?)""",
        (rfp_run_id, created_at, json.dumps(criteria_snapshot), provider, model, weight_warning),
    )
    conn.commit()
    conn.close()


def set_run_status(rfp_run_id, status):
    conn = get_connection()
    conn.execute("UPDATE rfp_runs SET status = ? WHERE rfp_run_id = ?", (status, rfp_run_id))
    conn.commit()
    conn.close()


def upsert_supplier_result(rfp_run_id, supplier_name, submission_date, experience_rating,
                            is_incumbent, incumbent_performance_rating, eval_status,
                            absolute_score=None, ppi=None, final_rank=None,
                            warnings=None, result_payload=None):
    conn = get_connection()
    conn.execute(
        """INSERT INTO supplier_results
           (rfp_run_id, supplier_name, submission_date, experience_rating, is_incumbent,
            incumbent_performance_rating, eval_status, absolute_score, ppi, final_rank,
            warnings_json, result_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(rfp_run_id, supplier_name) DO UPDATE SET
             submission_date=excluded.submission_date,
             experience_rating=excluded.experience_rating,
             is_incumbent=excluded.is_incumbent,
             incumbent_performance_rating=excluded.incumbent_performance_rating,
             eval_status=excluded.eval_status,
             absolute_score=excluded.absolute_score,
             ppi=excluded.ppi,
             final_rank=excluded.final_rank,
             warnings_json=excluded.warnings_json,
             result_json=excluded.result_json
        """,
        (rfp_run_id, supplier_name, submission_date, experience_rating, int(is_incumbent),
         incumbent_performance_rating, eval_status, absolute_score, ppi, final_rank,
         json.dumps(warnings or []), json.dumps(result_payload) if result_payload is not None else None),
    )
    conn.commit()
    conn.close()


def get_run(rfp_run_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM rfp_runs WHERE rfp_run_id = ?", (rfp_run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_supplier_results(rfp_run_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM supplier_results WHERE rfp_run_id = ? ORDER BY final_rank IS NULL, final_rank",
        (rfp_run_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_runs():
    conn = get_connection()
    rows = conn.execute("SELECT * FROM rfp_runs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]
