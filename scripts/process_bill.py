"""Run the full extraction agent on one bill and show what it did.

Usage:  python -m scripts.process_bill eval/dataset/private/cattle_feed.png --provider ollama
        python -m scripts.process_bill eval/dataset/private/agro.png --provider gemini --fallback ollama
"""
import argparse
import mimetypes
import sys
from pathlib import Path

from backend.app.extraction.agent import process_bill
from backend.app.extraction.prompts import EXTRACTION_PROMPT
from backend.app.extraction.providers.factory import get_provider

parser = argparse.ArgumentParser(description="Process one bill with the extraction agent")
parser.add_argument("image")
parser.add_argument("--provider", help="main provider: ollama or gemini (default from .env)")
parser.add_argument("--fallback", help="provider to use if the main one fails")
parser.add_argument("--json", action="store_true", help="also print the final extraction as JSON")
args = parser.parse_args()

path = Path(args.image)
if not path.exists():
    sys.exit(f"File not found: {path}")

result = process_bill(
    path.read_bytes(),
    mimetypes.guess_type(path)[0] or "image/jpeg",
    EXTRACTION_PROMPT,
    get_provider(args.provider),
    fallback=get_provider(args.fallback) if args.fallback else None,
)

print("Steps:")
for step in result.steps:
    print(f"  - {step}")
print(f"Model calls: {result.model_calls}")

for n, (entry, review) in enumerate(zip(result.document.entries, result.needs_review), start=1):
    print(f"\nEntry {n}: {entry.vendor_name} | bill {entry.bill_number} | {entry.date_as_written} | total {entry.total}")
    print(f"  Needs review: {', '.join(review) if review else 'nothing'}")

for label, items in (("Corrections made", result.corrections), ("Suggestions for the reviewer", result.suggestions)):
    if items:
        print(f"\n{label}:")
        for item in items:
            print(f"  - {item}")

if args.json:
    print("\n" + result.document.model_dump_json(indent=2))
