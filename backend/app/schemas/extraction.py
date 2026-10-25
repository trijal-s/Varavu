from typing import Literal
from pydantic import BaseModel, Field

DocumentType = Literal["tax_invoice", "bill_of_supply", "cash_bill", "estimate",
    "quotation", "challan", "notebook_page", "other",]
TransactionType=Literal["purchase", "sale", "expense", "unknown"]
PaymentMode=Literal["cash", "upi", "card", "credit", "unknown"]

class LineItem(BaseModel):
    description: str = Field(description="Item or service exactly as written, e.g. 'R.R' or 'Cattle feed'")
    quantity: float | None = Field(None, description="Quantity, days or bags as written")
    unit: str | None = Field(None, description="Unit such as pcs, kg, bags, days. Empty if not written")
    rate: float | None = Field(None, description="Price per unit as written")
    amount: float | None = Field(None, description="Line total as written. Do not calculate it")
    hsn_code: str | None = Field(None, description="HSN/SAC code if printed")
    taxable_amount: float | None = Field(None, description="Line amount before tax, if a separate column exists")
    tax_amount: float | None = Field(None, description="GST or VAT amount for this line, if shown")
    tax_rate: float | None = Field(None, description="GST or VAT percent for this line, e.g. 18")

class BillEntry(BaseModel):
    vendor_name: str | None = Field(None, description="Shop or company that issued the bill (printed header)")
    vendor_phone: str | None = Field(None, description="Vendor phone number as printed")
    vendor_gstin: str | None = Field(None, description="15-character GSTIN of the vendor, if printed")
    party_name: str | None = Field(None, description="Customer name written after 'To', 'M/s' or 'Name'")
    bill_number: str | None = Field(None, description="Invoice, bill or memo number")
    date_as_written: str | None = Field(None, description="Bill date exactly as written, e.g. '28/3/24'. Do not reformat")
    transaction_type: TransactionType = Field("unknown", description="purchase if the shop owner bought, sale if sold, expense for services like rent or repair")
    line_items: list[LineItem] = Field(default_factory=list, description="One entry per filled row. Skip empty rows and bank details")
    subtotal: float | None = Field(None, description="Total before tax, if written")
    cgst: float | None = Field(None, description="CGST amount in rupees")
    sgst: float | None = Field(None, description="SGST amount in rupees")
    igst: float | None = Field(None, description="IGST amount in rupees")
    discount: float | None = Field(None, description="Discount amount, if any")
    total: float | None = Field(None, description="Final bill total as written. Do not calculate it")
    total_in_words: str | None = Field(None, description="Total amount written in words, copied exactly")
    tax_inclusive: bool | None = Field(None, description="True if prices already include tax")
    amount_paid: float | None = Field(None, description="Advance or amount paid, if written")
    balance_due: float | None = Field(None, description="Balance remaining. 'NIL' means 0")
    payment_mode: PaymentMode = Field("unknown", description="cash, upi, card or credit if stated")
    low_confidence_fields: list[str] = Field(default_factory=list, description="Names of fields you could not read clearly")


class DocumentExtraction(BaseModel):
    document_type: DocumentType = Field(description="Kind of document in the photo")
    is_readable: bool = Field(description="False if the photo is too blurry or dark to read")
    is_obscured: bool = Field(description="True if a finger, object or fold hides part of the bill")
    entries: list[BillEntry] = Field(default_factory=list, description="One entry per bill. A notebook page may have many")