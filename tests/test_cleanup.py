from backend.app.extraction.cleanup import clean_document
from backend.app.schemas.extraction import BillEntry, DocumentExtraction, LineItem


def make_doc(**entry_fields) -> DocumentExtraction:
    return DocumentExtraction(document_type="cash_bill", is_readable=True, is_obscured=False,
                              entries=[BillEntry(**entry_fields)])


def test_placeholders_become_empty():
    doc = clean_document(make_doc(vendor_gstin="", party_name="  -  ",
                                  line_items=[LineItem(description="BALIO", hsn_code="0")]))
    entry = doc.entries[0]
    assert entry.vendor_gstin is None
    assert entry.party_name is None
    assert entry.line_items[0].hsn_code is None


def test_zero_tax_becomes_empty_but_zero_balance_stays():
    entry = clean_document(make_doc(cgst=0.0, igst=0.0, balance_due=0.0)).entries[0]
    assert entry.cgst is None and entry.igst is None
    assert entry.balance_due == 0.0


def test_unknown_low_confidence_fields_removed():
    entry = clean_document(make_doc(low_confidence_fields=["party_name", "bank_name"])).entries[0]
    assert entry.low_confidence_fields == ["party_name"]


def test_extra_spaces_collapsed():
    assert clean_document(make_doc(vendor_name="PREET   PALACE ")).entries[0].vendor_name == "PREET PALACE"
