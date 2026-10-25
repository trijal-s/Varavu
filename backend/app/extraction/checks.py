"""Checks that catch wrong numbers by comparing values on the bill with each other.

Each check returns a list of Issue objects. An empty list means everything agrees.
"""
import re
from dataclasses import dataclass

from backend.app.extraction.amount_words import words_to_amount
from backend.app.extraction.dates import check_date, financial_year_start, parse_bill_date
from backend.app.schemas.extraction import BillEntry

TOLERANCE = 1.0  # rupees, to allow for rounding on the bill

GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@dataclass
class Issue:
    field: str     # which field looks wrong, e.g. "total" or "line_items[2].amount"
    message: str   # a short explanation a person can act on


def close(a: float, b: float) -> bool:
    return abs(a - b) <= TOLERANCE


def check_line_items(entry: BillEntry) -> list[Issue]:
    """Each row: quantity x rate should equal the amount (or the before-tax amount)."""
    issues = []
    for i, item in enumerate(entry.line_items):
        if item.quantity is None or item.rate is None or item.amount is None:
            continue
        product = item.quantity * item.rate
        if close(product, item.amount):
            continue
        if item.taxable_amount is not None and close(product, item.taxable_amount):
            continue
        issues.append(Issue(f"line_items[{i}].amount",
                            f"{item.quantity:g} x {item.rate:g} = {product:.2f}, but amount is {item.amount:.2f}"))
    return issues


def check_total(entry: BillEntry) -> list[Issue]:
    """The total should match the sum of the rows, or subtotal plus taxes."""
    if entry.total is None:
        return [Issue("total", "total is missing")]

    amounts = [item.amount for item in entry.line_items if item.amount is not None]
    if amounts and close(sum(amounts), entry.total):
        return []

    taxes = sum(t for t in (entry.cgst, entry.sgst, entry.igst) if t is not None)
    discount = entry.discount or 0
    if entry.subtotal is not None and close(entry.subtotal + taxes - discount, entry.total):
        return []

    if not amounts and entry.subtotal is None:
        return []  # nothing to compare against
    expected = sum(amounts) if amounts else entry.subtotal + taxes - discount
    return [Issue("total", f"rows add up to {expected:.2f}, but total is {entry.total:.2f}")]


def check_total_in_words(entry: BillEntry) -> list[Issue]:
    if not entry.total_in_words or entry.total is None:
        return []
    amount = words_to_amount(entry.total_in_words)
    if amount is None:
        return [Issue("total_in_words", f"could not read '{entry.total_in_words}' as a number")]
    if not close(amount, entry.total):
        return [Issue("total", f"total is {entry.total:.2f}, but words say {amount:.2f}")]
    return []


def gstin_checksum_ok(gstin: str) -> bool:
    """The 15th character of a GSTIN is a checksum of the first 14."""
    total = 0
    for i, char in enumerate(gstin[:14]):
        product = GSTIN_CHARS.index(char) * (1 if i % 2 == 0 else 2)
        total += product // 36 + product % 36
    return GSTIN_CHARS[(36 - total % 36) % 36] == gstin[14]


def check_gstin(entry: BillEntry) -> list[Issue]:
    if not entry.vendor_gstin:
        return []
    gstin = entry.vendor_gstin.replace(" ", "").upper()
    if not GSTIN_RE.match(gstin):
        return [Issue("vendor_gstin", f"'{entry.vendor_gstin}' is not in GSTIN format (15 characters)")]
    if not gstin_checksum_ok(gstin):
        return [Issue("vendor_gstin", f"'{entry.vendor_gstin}' fails the GSTIN checksum; probably misread")]
    return []


def check_entry_date(entry: BillEntry) -> list[Issue]:
    bill_date = parse_bill_date(entry.date_as_written)
    problems = check_date(bill_date, financial_year_start(entry.bill_number))
    return [Issue("date_as_written", p) for p in problems]


def run_checks(entry: BillEntry) -> list[Issue]:
    """Run every check on one bill entry."""
    return (check_line_items(entry) + check_total(entry) + check_total_in_words(entry)
            + check_gstin(entry) + check_entry_date(entry))
