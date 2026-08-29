"""One-off live validation script: runs the full pipeline against a REAL model
using an API key from the ANTHROPIC_LIVE_KEY environment variable. Not part of
the delivered test suite (costs real API calls) -- run manually to sanity-check
the live path before submission."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.seed import init_db
from db import repository as repo
import orchestrator as orch
from tools.llm_providers import get_provider
from data.synthetic.content import ALL_SUPPLIERS, SUGGESTED_METADATA

SYNTH_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "synthetic")

key = os.environ.get("ANTHROPIC_LIVE_KEY")
if not key:
    print("Set ANTHROPIC_LIVE_KEY env var first.")
    sys.exit(1)

init_db()
active_criteria = repo.get_active_criteria()
provider = get_provider("Anthropic", key, "claude-sonnet-4-5-20250929")

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

batch = orch.create_batch(active_criteria, "Anthropic", "claude-sonnet-4-5-20250929", "buyer context", supplier_inputs)

for s in batch.suppliers:
    print(f"Evaluating {s.input.supplier_name} (live API call)...")
    orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)
    if s.eval_status == "FAILED":
        print(f"  FAILED: {s.error_message}")
    else:
        print(f"  OK, {len(s.validated_results)} criteria scored")

print()
print("All succeeded:", orch.all_suppliers_succeeded(batch))
if orch.all_suppliers_succeeded(batch):
    orch.finalize_ranking(batch)
    print()
    print("LEADERBOARD:")
    for s in sorted(batch.suppliers, key=lambda s: s.final_rank):
        print(f"  #{s.final_rank} {s.input.supplier_name:25s} abs={s.absolute_score:6.2f}  ppi={s.ppi:8.4f}")
    print()
    print("WARNINGS (evidence issues, clips, etc.):")
    for s in batch.suppliers:
        for w in s.run_warnings:
            print(f"  [{s.input.supplier_name}] {w}")
    print()
    vantage = next(s for s in batch.suppliers if "Vantage" in s.input.supplier_name)
    print("VANTAGE (adversarial) rank:", vantage.final_rank, "risks:", vantage.raw_llm_result.get("risks"))
else:
    for s in batch.suppliers:
        if s.eval_status == "FAILED":
            print("FAILED SUPPLIER:", s.input.supplier_name, s.error_message)
