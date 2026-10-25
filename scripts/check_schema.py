import json
from backend.app.schemas.extraction import DocumentExtraction

print(json.dumps(DocumentExtraction.model_json_schema(), indent=2)[:1500])

sample = {"document_type": "cash_bill", "is_readable": True, "is_obscured": False,
          "entries": [{"vendor_name": "Preet Palace", "date_as_written": "29/3/24",
                       "line_items": [{"description": "R.R", "quantity": 1, "rate": 2300, "amount": 2300}],
                       "total": 2300, "amount_paid": 2300, "balance_due": 0}]}
doc = DocumentExtraction.model_validate(sample)
print(doc.entries[0].line_items[0].amount)