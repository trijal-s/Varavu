"""Compare one model extraction with its label, field by field."""
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem

# Fields we don't score yet (see NOTES.md for why).
SKIP_FIELDS = {"transaction_type", "low_confidence_fields", "line_items"}
NUMBER_TOLERANCE = 0.5  # rupees

# The five possible outcomes for one field.
CORRECT, WRONG, MISSED, INVENTED, BOTH_EMPTY = "correct", "wrong", "missed", "invented", "both_empty"


def is_empty(value) -> bool:
    """None, empty text and 'unknown' all mean 'not on the bill'."""
    if value is None:
        return True
    return isinstance(value, str) and value.strip().lower() in ("", "unknown")


def normalize_text(value: str) -> str:
    """Ignore case and extra spaces: 'PREET  Palace' matches 'Preet Palace'."""
    return " ".join(value.lower().split())


def compare_value(expected, predicted) -> str:
    if is_empty(expected) and is_empty(predicted):
        return BOTH_EMPTY
    if is_empty(predicted):
        return MISSED
    if is_empty(expected):
        return INVENTED
    if isinstance(expected, bool) or isinstance(predicted, bool):
        return CORRECT if expected == predicted else WRONG
    if isinstance(expected, (int, float)) and isinstance(predicted, (int, float)):
        return CORRECT if abs(expected - predicted) <= NUMBER_TOLERANCE else WRONG
    return CORRECT if normalize_text(str(expected)) == normalize_text(str(predicted)) else WRONG


def compare_items(expected: list[LineItem], predicted: list[LineItem]) -> dict[str, list[str]]:
    """Compare line items row by row, in order. Missing rows count as missed or invented."""
    outcomes: dict[str, list[str]] = {}
    for i in range(max(len(expected), len(predicted))):
        exp = expected[i] if i < len(expected) else None
        pred = predicted[i] if i < len(predicted) else None
        for field in LineItem.model_fields:
            e = getattr(exp, field) if exp else None
            p = getattr(pred, field) if pred else None
            outcomes.setdefault(f"item.{field}", []).append(compare_value(e, p))
    return outcomes


def compare_document(expected: DocumentExtraction, predicted: DocumentExtraction) -> dict[str, list[str]]:
    """Return {field name: [outcome, ...]} for one bill."""
    outcomes = {"document_type": [compare_value(expected.document_type, predicted.document_type)]}
    outcomes["entry_count"] = [CORRECT if len(expected.entries) == len(predicted.entries) else WRONG]

    # Most bills have one entry; notebook pages with many entries are compared in order.
    for i in range(max(len(expected.entries), len(predicted.entries))):
        exp = expected.entries[i] if i < len(expected.entries) else BillEntry()
        pred = predicted.entries[i] if i < len(predicted.entries) else BillEntry()
        for field in BillEntry.model_fields:
            if field not in SKIP_FIELDS:
                outcomes.setdefault(field, []).append(compare_value(getattr(exp, field), getattr(pred, field)))
        for field, results in compare_items(exp.line_items, pred.line_items).items():
            outcomes.setdefault(field, []).extend(results)
    return outcomes
