from typing import Literal
from pydantic import BaseModel, Field
DocumentType = Literal["tax_invoice","bill_of_supply","cash_bill","estimate","quotation","challan","notebook_page","other"]
TransactionType = Literal["purchase","sale","expense","unknown"]
PaymentMode = Literal["cash","upi","card","credit","unknown"]
class LineItem(BaseModel):
    description: str
    quantity: float|None=None; unit: str|None=None; rate: float|None=None; amount: float|None=None
    hsn_code: str|None=None; tax_rate: float|None=None; taxable_amount: float|None=None; tax_amount: float|None=None
class BillEntry(BaseModel):
    vendor_name: str|None=None; vendor_phone: str|None=None; vendor_gstin: str|None=None; party_name: str|None=None
    bill_number: str|None=None; date_as_written: str|None=None; transaction_type: TransactionType="unknown"
    line_items: list[LineItem]=Field(default_factory=list)
    subtotal: float|None=None; cgst: float|None=None; sgst: float|None=None; igst: float|None=None; discount: float|None=None
    total: float|None=None; total_in_words: str|None=None; tax_inclusive: bool|None=None
    amount_paid: float|None=None; balance_due: float|None=None; payment_mode: PaymentMode="unknown"
    low_confidence_fields: list[str]=Field(default_factory=list)
class DocumentExtraction(BaseModel):
    document_type: DocumentType; is_readable: bool; is_obscured: bool
    entries: list[BillEntry]=Field(default_factory=list)
