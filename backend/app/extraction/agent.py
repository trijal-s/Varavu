"""The extraction agent: read a bill, check it, and act on problems.

Flow for one bill:
  1. Extract with the main provider (fall back to a second provider if it fails).
  2. Clean up and run the checks. If everything passes, we're done.
  3. Otherwise re-read the bill once, telling the model exactly what looked wrong,
     and keep whichever reading has fewer problems.
  4. Apply safe fixes in code (only when two independent parts of the bill agree).
  5. Anything still wrong is flagged for a person to confirm. Nothing is guessed.
"""
from dataclasses import dataclass, field

from backend.app.extraction.checks import Issue, close, run_checks
from backend.app.extraction.cleanup import clean_document
from backend.app.extraction.amount_words import words_to_amount
from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.schemas.extraction import BillEntry, DocumentExtraction

REREAD_NOTE = """

A previous reading of this bill had these problems:
{problems}
Look at these parts of the bill again very carefully, digit by digit, and return the full bill."""


@dataclass
class AgentResult:
    document: DocumentExtraction
    issues: list[list[Issue]]           # remaining problems, one list per entry
    needs_review: list[list[str]]       # fields a person must confirm, one list per entry
    suggestions: list[str] = field(default_factory=list)  # hints for the reviewer
    corrections: list[str] = field(default_factory=list)  # changes made automatically
    steps: list[str] = field(default_factory=list)        # what the agent did, in order
    model_calls: int = 0


def count_issues(doc: DocumentExtraction) -> int:
    return sum(len(run_checks(entry)) for entry in doc.entries)


def describe(doc: DocumentExtraction) -> str:
    lines = [f"- {issue.field}: {issue.message}" for entry in doc.entries for issue in run_checks(entry)]
    return "\n".join(lines)


def apply_safe_fixes(entry: BillEntry, suggestions: list[str], corrections: list[str]) -> BillEntry:
    """Fix only what two independent parts of the bill agree on; otherwise just suggest."""
    entry = entry.model_copy(deep=True)
    amounts = [item.amount for item in entry.line_items if item.amount is not None]
    rows_sum = sum(amounts) if amounts else None
    words = words_to_amount(entry.total_in_words)

    # Total: if the rows and the amount in words agree with each other, they outvote the total.
    if entry.total is not None and rows_sum is not None and not close(rows_sum, entry.total):
        if words is not None and close(words, rows_sum):
            corrections.append(f"total changed from {entry.total:.2f} to {rows_sum:.2f} (rows and words agree)")
            entry.total = rows_sum
        else:
            suggestions.append(f"total: rows add up to {rows_sum:.2f}")

    # Rows: if the amounts add up to the total, trust the amounts and point at the rate.
    total_ok = entry.total is not None and rows_sum is not None and close(rows_sum, entry.total)
    for i, item in enumerate(entry.line_items):
        if item.quantity and item.rate is not None and item.amount is not None:
            product = item.quantity * item.rate
            if not close(product, item.amount) and not (item.taxable_amount and close(product, item.taxable_amount)):
                if total_ok:
                    suggestions.append(f"line_items[{i}].rate: likely {item.amount / item.quantity:.2f} "
                                       f"(amount {item.amount:.2f} / quantity {item.quantity:g})")

    # GSTIN: text that isn't even GSTIN-shaped is not a GSTIN. Remove it rather than store it.
    for issue in run_checks(entry):
        if issue.field == "vendor_gstin" and "not in GSTIN format" in issue.message:
            corrections.append(f"removed '{entry.vendor_gstin}' from vendor_gstin (not a valid GSTIN)")
            entry.vendor_gstin = None
    return entry


def review_fields(entry: BillEntry, issues: list[Issue]) -> list[str]:
    """Fields a person must confirm: anything a check still complains about, plus what the model was unsure of."""
    fields = [issue.field for issue in issues]
    for issue in issues:  # a row problem usually means the rate or quantity was misread
        if issue.field.startswith("line_items[") and issue.field.endswith(".amount"):
            fields.append(issue.field.replace(".amount", ".rate"))
    fields += entry.low_confidence_fields
    return sorted(set(fields))


def process_bill(image_bytes: bytes, mime_type: str, prompt: str, provider: ExtractionProvider,
                 fallback: ExtractionProvider | None = None, max_rereads: int = 1) -> AgentResult:
    steps, calls = [], 0

    def extract(text: str) -> DocumentExtraction:
        nonlocal calls
        calls += 1
        try:
            return clean_document(provider.extract(image_bytes, mime_type, text))
        except Exception as error:
            if fallback is None:
                raise
            steps.append(f"{provider.name} failed ({type(error).__name__}); using {fallback.name}")
            return clean_document(fallback.extract(image_bytes, mime_type, text))

    # 1-2. First reading and checks.
    best = extract(prompt)
    best_count = count_issues(best)
    steps.append(f"read bill: {len(best.entries)} entries, {best_count} problems")

    if not best.is_readable or best.is_obscured:
        steps.append("photo unreadable or partly covered; asking for a retake is recommended")

    # 3. Re-read with the problems spelled out, keep the better reading.
    for _ in range(max_rereads):
        if best_count == 0:
            break
        candidate = extract(prompt + REREAD_NOTE.format(problems=describe(best)))
        candidate_count = count_issues(candidate)
        steps.append(f"re-read: {candidate_count} problems (was {best_count})")
        if candidate_count < best_count:
            best, best_count = candidate, candidate_count

    # 4. Safe fixes in code.
    suggestions, corrections = [], []
    fixed_entries = [apply_safe_fixes(entry, suggestions, corrections) for entry in best.entries]
    best = best.model_copy(update={"entries": fixed_entries})
    if corrections:
        steps.append(f"applied {len(corrections)} safe fix(es)")

    # 5. Whatever is left goes to a person.
    issues = [run_checks(entry) for entry in best.entries]
    needs_review = [review_fields(entry, entry_issues) for entry, entry_issues in zip(best.entries, issues)]
    remaining = sum(len(i) for i in issues)
    steps.append("all checks passed" if remaining == 0 else f"{remaining} problem(s) left for review")

    return AgentResult(best, issues, needs_review, suggestions, corrections, steps, calls)
