# Varavu development notes

## Setup
- Python 3.14, virtual environment in `venv/`
- Extraction provider: Ollama (local)
- Model: qwen2.5vl:7b  <!-- change if you use 3b -->
- Run scripts from the repo root with `python -m scripts.<name>`

## Daily log

### Day 1: Extraction schema
- Built `backend/app/schemas/extraction.py`: `LineItem`, `BillEntry`, `DocumentExtraction`
- Learned: Pydantic models, optional fields, `Field(description=...)`, `Literal` choices
- Problem: pasting many lines into the Python shell got stuck at `...`
- Fix: put test code in `scripts/check_schema.py` and run it with `python -m`

### Day 2: First real extraction
- Built `providers/base.py` (interface), `providers/ollama.py`, `scripts/try_extract.py`
- Errors and fixes:
  - `IndexError`: ran the script without an image path
  - `FileNotFoundError`: used the placeholder path instead of a real file
  - `model not found (404)`: model wasn't pulled; fixed with `ollama pull`
- First result: model read only the GST summary table and returned it as two bills

### Day 3: Labels
- Started labeled test set; `agro.json` done
- Next: hotel, cattle_feed, sd_enterprise, furniture_bill_of_supply

## Experiments (change one thing at a time)

| # | Change | Bill | Result | Kept? |
|---|---|---|---|---|
| 1 | `num_ctx` 8192 | agro | Output identical, so context size was not the problem | Yes (harmless) |
| 2 | Detailed prompt | agro | Big improvement: bill number, date, all 7 items and totals correct | Yes |
| 3 | Added `taxable_amount`, `tax_amount`; prompt lines for GSTIN, phone, party | agro | IGST no longer invented. Model switched to the rate-incl-tax column, so rows now add up. GSTIN, phone, party still missing. `tax_rate` accidentally removed from schema | Partly |
| 4 | Upscale image 3x | agro | TODO | |
Amount/total instruction fix | hotel | amount and total restored; invented zeros and subtotal gone. Remaining: empty-string GSTIN, arrival date, invented words, cash guess | Yes

## Labeling rules
1. If a bill has two rate columns, `rate` is the rate including tax, so quantity x rate = amount. Pre-tax line value goes in `taxable_amount`.
2. A printed "0" used as a placeholder (e.g. HSN column) is stored as null.
3. Copy text exactly as printed. For the vendor name, use the English version if the bill shows one.
4. `payment_mode` is `unknown` unless the bill says cash, UPI, card or credit.
5. Missing values are null, never 0.
6. `transaction_type` is `unknown` in test labels for now (no shop context yet).

## Results per bill

| Bill | Difficulty | Time per run | Main problems |
|---|---|---|---|
| agro | easy | ? | Tiny header text missed; NANOMOL read as NANOMDL |
| hotel | medium | | |
| cattle_feed | hard | | |

## Known issues and TODO
- [ ] Restore `tax_rate` in `LineItem`
- [ ] Measure time per bill
- [ ] Try upscaling small images (experiment 4)
- [ ] Work out `tax_inclusive` in code instead of asking the model
- [ ] Move `PROMPT` into `backend/app/extraction/prompts.py`

Upscale 3x | agro | NANOMOL fixed. GSTIN, phone, party still missing (now flagged low-confidence). Rate column flipped back to before-tax price; IGST 0 and “cash” guesses returned | Yes, for small images

## Open questions
-

Gemini vs Ollama (2 bills): key fields 97.1% vs 50.0%; time ~12s vs 181s. Ollama returned no line items for agro with the detailed prompt (earlier simpler prompt worked). Decision: Gemini main; Ollama optional, may need its own prompt.