"""Extract one bill, clean it up, run the checks, and print any problems.

Usage:  python -m scripts.check_bill eval/dataset/private/cattle_feed.png --provider ollama
"""
import argparse
import mimetypes
import sys
from pathlib import Path

from backend.app.extraction.checks import run_checks
from backend.app.extraction.cleanup import clean_document
from backend.app.extraction.prompts import EXTRACTION_PROMPT
from backend.app.extraction.providers.factory import get_provider

parser = argparse.ArgumentParser(description="Extract a bill and check it")
parser.add_argument("image")
parser.add_argument("--provider", help="ollama or gemini (default from .env)")
args = parser.parse_args()

path = Path(args.image)
if not path.exists():
    sys.exit(f"File not found: {path}")

mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"
doc = clean_document(get_provider(args.provider).extract(path.read_bytes(), mime_type, EXTRACTION_PROMPT))

for n, entry in enumerate(doc.entries, start=1):
    print(f"Entry {n}: {entry.vendor_name} | bill {entry.bill_number} | {entry.date_as_written} | total {entry.total}")
    issues = run_checks(entry)
    if not issues:
        print("  All checks passed")
    for issue in issues:
        print(f"  PROBLEM  {issue.field}: {issue.message}")
