"""Generates data/sample_run_export.json -- the brief's required 'sample exported
JSON for one completed RFP run', produced by actually running the pipeline in
demo mode (not hand-written) so it is a real, valid example of the export format."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.seed import init_db
from db import repository as repo
import orchestrator as orch
from tools.demo_provider import DemoProvider
from data.synthetic.content import ALL_SUPPLIERS, SUGGESTED_METADATA

SYNTH_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic")
OUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sample_run_export.json")


def main():
    init_db()
    active_criteria = repo.get_active_criteria()
    provider = DemoProvider()

    supplier_inputs = []
    for supplier in ALL_SUPPLIERS:
        safe_name = supplier["supplier_name"].replace(" ", "_").replace(".", "")
        path = os.path.join(SYNTH_DIR, f"Supplier_{safe_name}.pdf")
        with open(path, "rb") as f:
            file_bytes = f.read()
        meta = SUGGESTED_METADATA[supplier["supplier_name"]]
        supplier_inputs.append(orch.SupplierInput(
            supplier_name=supplier["supplier_name"], file_bytes=file_bytes,
            submission_date=meta["submission_date"], experience_rating=meta["experience_rating"],
            is_incumbent=meta["is_incumbent"], incumbent_performance_rating=meta["incumbent_performance_rating"],
        ))

    batch = orch.create_batch(active_criteria, "Demo", "canned-v1", "buyer context", supplier_inputs)
    for s in batch.suppliers:
        orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)
    orch.finalize_ranking(batch)

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
    with open(OUT_PATH, "w") as f:
        json.dump(export_payload, f, indent=2, default=str)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
