"""Clean up model output before it is checked or saved.

The model copies what it sees, including placeholders like "0" or "-", and sometimes
writes 0 for tax that isn't on the bill. These rules fix that in code, so we don't
have to keep fighting the model with prompt instructions.
"""
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem

# Text that means "nothing written here".
PLACEHOLDERS = {"", "0", "-", "--", "nil", "na", "n/a", "null", "none"}

# For tax, 0 and "not on the bill" mean the same thing, so we store both as empty.
# (balance_due is NOT here: a balance of 0, written as NIL, is real information.)
ZERO_MEANS_EMPTY = {"cgst", "sgst", "igst", "discount"}
ITEM_ZERO_MEANS_EMPTY = {"tax_rate", "tax_amount"}

KNOWN_FIELDS = set(BillEntry.model_fields) | set(LineItem.model_fields)


def clean_text(value: str | None) -> str | None:
    """Collapse extra spaces; turn placeholders into None."""
    if value is None:
        return None
    value = " ".join(value.split())
    return None if value.lower() in PLACEHOLDERS else value


def clean_fields(data: dict, zero_fields: set[str]) -> dict:
    for field, value in data.items():
        if isinstance(value, str) and field not in ("transaction_type", "payment_mode"):
            data[field] = clean_text(value)
        elif field in zero_fields and value == 0:
            data[field] = None
    return data


def clean_entry(entry: BillEntry) -> BillEntry:
    data = clean_fields(entry.model_dump(), ZERO_MEANS_EMPTY)

    items = []
    for item in data["line_items"]:
        item = clean_fields(item, ITEM_ZERO_MEANS_EMPTY)
        if item["description"]:  # a row with no description is an empty row
            items.append(item)
    data["line_items"] = items

    # Keep only real field names (the model sometimes lists fields that don't exist).
    data["low_confidence_fields"] = [f for f in data["low_confidence_fields"] if f in KNOWN_FIELDS]
    return BillEntry.model_validate(data)


def clean_document(doc: DocumentExtraction) -> DocumentExtraction:
    return doc.model_copy(update={"entries": [clean_entry(e) for e in doc.entries]})
