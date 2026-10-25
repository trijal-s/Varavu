EXTRACTION_PROMPT = """You are reading a photo of an Indian bill. Copy what is written; never guess.

Document type: tax_invoice only if titled Tax Invoice; bill_of_supply only if titled Bill of Supply;
cash_bill for other bills; quotation or estimate if marked so; notebook_page for ledger pages.

One bill = ONE entry. GST summary tables and bank details are not separate bills.
- vendor_name, vendor_phone, vendor_gstin: from the printed header
- party_name: customer name after To, M/s or Name
- bill_number, date_as_written: copy exactly. If the invoice date is blank, use the checkout or completion date
- line_items: one per filled row. amount is the row total in the Amount column; always fill it if written.
     Fill taxable_amount only if the bill has a separate taxable or before-tax column.
- total: the final total on the bill; always fill it if written
- subtotal, cgst, sgst, igst: tax AMOUNTS in rupees, only if written
- total_in_words: only if words are actually written on the bill
- amount_paid: an ADVANCE or PAID amount; balance_due: the BALANCE (NIL means 0)
- payment_mode: unknown unless the bill says cash, UPI, card or credit

Leave any field empty if it is not on the bill. Never write 0 for a missing value."""