"""Agent tests use fake providers, so they run instantly and never call a real model."""
from backend.app.extraction.agent import process_bill
from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem


class FakeProvider(ExtractionProvider):
    """Returns prepared readings in order, like a model that answers differently each time."""
    name = "fake"

    def __init__(self, *readings):
        self.readings = list(readings)
        self.calls = 0

    def extract(self, image_bytes, mime_type, prompt):
        self.calls += 1
        return self.readings.pop(0)


class BrokenProvider(ExtractionProvider):
    name = "broken"

    def extract(self, image_bytes, mime_type, prompt):
        raise RuntimeError("service unavailable")


def bill(rate=580, total=30000, words=None, gstin=None) -> DocumentExtraction:
    rows = [LineItem(description="a", quantity=10, rate=810, amount=8100),
            LineItem(description="b", quantity=10, rate=1200, amount=12000),
            LineItem(description="c", quantity=5, rate=rate, amount=2900),
            LineItem(description="d", quantity=1, rate=2200, amount=2200),
            LineItem(description="e", quantity=4, rate=1200, amount=4800)]
    entry = BillEntry(bill_number="2361", date_as_written="22-2-21", line_items=rows,
                      total=total, total_in_words=words, vendor_gstin=gstin)
    return DocumentExtraction(document_type="cash_bill", is_readable=True, is_obscured=False, entries=[entry])


def run(provider, **kwargs):
    return process_bill(b"", "image/png", "prompt", provider, **kwargs)


def test_clean_bill_needs_one_call():
    provider = FakeProvider(bill())
    result = run(provider)
    assert provider.calls == 1
    assert result.issues == [[]]


def test_reread_fixes_misread_rate():
    provider = FakeProvider(bill(rate=680), bill(rate=580))
    result = run(provider)
    assert provider.calls == 2
    assert result.issues == [[]]
    assert result.document.entries[0].line_items[2].rate == 580


def test_rate_flagged_with_suggestion_when_reread_fails():
    provider = FakeProvider(bill(rate=680), bill(rate=680))
    result = run(provider)
    assert "line_items[2].rate" in result.needs_review[0]
    assert any("likely 580.00" in s for s in result.suggestions)


def test_total_fixed_when_rows_and_words_agree():
    misread = bill(total=303000, words="Thirty Thousand Rupees Only")
    result = run(FakeProvider(misread, misread))
    assert result.document.entries[0].total == 30000
    assert result.corrections


def test_total_not_changed_without_words():
    misread = bill(total=303000)
    result = run(FakeProvider(misread, misread))
    assert result.document.entries[0].total == 303000  # no second source: don't guess
    assert "total" in result.needs_review[0]


def test_invalid_gstin_removed():
    reading = bill(gstin="ABCD9218P")
    result = run(FakeProvider(reading, reading))
    assert result.document.entries[0].vendor_gstin is None


def test_fallback_provider_used_when_main_fails():
    result = run(BrokenProvider(), fallback=FakeProvider(bill()))
    assert result.issues == [[]]
    assert any("using fake" in step for step in result.steps)
