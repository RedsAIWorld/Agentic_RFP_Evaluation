import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from db.seed import init_db
from db import repository as repo
import orchestrator as orch
from tools.demo_provider import DemoProvider
from data.synthetic.content import ALL_SUPPLIERS, SUGGESTED_METADATA

init_db()
active_criteria = repo.get_active_criteria()
provider = DemoProvider()

supplier_inputs = []
for supplier in ALL_SUPPLIERS:
    safe_name = supplier['supplier_name'].replace(' ', '_').replace('.', '')
    path = os.path.join('data/synthetic', f'Supplier_{safe_name}.pdf')
    with open(path, 'rb') as f:
        file_bytes = f.read()
    meta = SUGGESTED_METADATA[supplier['supplier_name']]
    supplier_inputs.append(orch.SupplierInput(
        supplier_name=supplier['supplier_name'], file_bytes=file_bytes,
        submission_date=meta['submission_date'], experience_rating=meta['experience_rating'],
        is_incumbent=meta['is_incumbent'], incumbent_performance_rating=meta['incumbent_performance_rating'],
    ))

batch = orch.create_batch(active_criteria, 'Demo', 'canned-v1', 'buyer context', supplier_inputs)
for s in batch.suppliers:
    orch.run_evaluation_for_supplier(s, batch.llm_criteria, batch.buyer_context, provider)

print('All succeeded:', orch.all_suppliers_succeeded(batch))
orch.finalize_ranking(batch)

print()
print('LEADERBOARD:')
for s in sorted(batch.suppliers, key=lambda s: s.final_rank):
    print(f'  #{s.final_rank} {s.input.supplier_name:25s} abs={s.absolute_score:6.2f}  ppi={s.ppi:8.4f}  {s.tie_break_reason}')

print()
print('EVIDENCE VERIFICATION CHECK (expect Orbit Digital Security hallucination flagged):')
for s in batch.suppliers:
    for w in s.run_warnings:
        if 'hallucination' in w.lower() or 'unverif' in w.lower():
            print(f'  [{s.input.supplier_name}] {w}')

print()
print('INJECTION DEFENSE CHECK (Vantage):')
vantage = next(s for s in batch.suppliers if 'Vantage' in s.input.supplier_name)
print('  Vantage rank:', vantage.final_rank, ' abs score:', vantage.absolute_score)
print('  Vantage raw risks:', vantage.raw_llm_result.get('risks'))
