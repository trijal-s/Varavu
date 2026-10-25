from backend.app.extraction.checks import check_gstin, check_line_items, check_total, check_total_in_words
from backend.app.schemas.extraction import BillEntry, LineItem

CATTLE_FEED_ROWS = [
    LineItem(description="feed 1", quantity=10, rate=810, amount=8100),
    LineItem(description="feed 2", quantity=10, rate=1200, amount=12000),
    LineItem(description="feed 3", quantity=5, rate=580, amount=2900),
    LineItem(description="feed 4", quantity=1, rate=2200, amount=2200),
    LineItem(description="feed 5", quantity=4, rate=1200, amount=4800),
]


def test_total_misread_is_caught():
    # The Ollama result on the cattle feed bill: rows add up to 30000, total read as 303000.
    issues = check_total(BillEntry(line_items=CATTLE_FEED_ROWS, total=303000))
    assert len(issues) == 1 and issues[0].field == "total"


def test_correct_total_passes():
    assert check_total(BillEntry(line_items=CATTLE_FEED_ROWS, total=30000)) == []


def test_subtotal_plus_tax_passes():
    entry = BillEntry(subtotal=2715.94, cgst=227.03, sgst=227.03, total=3170.0)
    assert check_total(entry) == []


def test_row_arithmetic():
    good = LineItem(description="x", quantity=3, rate=280, amount=840)
    before_tax = LineItem(description="x", quantity=3, rate=237.29, amount=840, taxable_amount=711.87)
    bad = LineItem(description="x", quantity=3, rate=280, amount=940)
    assert check_line_items(BillEntry(line_items=[good, before_tax])) == []
    assert len(check_line_items(BillEntry(line_items=[bad]))) == 1


def test_words_must_match_total():
    words = "Three Thousand One Hundred And Seventy Rupees"
    assert check_total_in_words(BillEntry(total=3170, total_in_words=words)) == []
    assert len(check_total_in_words(BillEntry(total=3710, total_in_words=words))) == 1


def test_gstin():
    assert check_gstin(BillEntry(vendor_gstin="33BUQPB4015B1ZA")) == []      # real GSTIN from the agro bill
    assert len(check_gstin(BillEntry(vendor_gstin="ABEC09218P"))) == 1       # too short
    assert len(check_gstin(BillEntry(vendor_gstin="33BUQPB4015B1ZB"))) == 1  # one character misread
