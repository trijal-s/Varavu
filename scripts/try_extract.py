import argparse
import mimetypes
import sys
import time
from pathlib import Path

from backend.app.extraction.prompts import EXTRACTION_PROMPT
from backend.app.extraction.providers.factory import get_provider

parser = argparse.ArgumentParser(description="Extract one bill image into structured JSON")
parser.add_argument("image", help="Path to the bill image")
parser.add_argument("--provider", help="ollama or gemini (default: EXTRACTION_PROVIDER in .env)")
args = parser.parse_args()

path = Path(args.image)
if not path.exists():
    sys.exit(f"File not found: {path}")
mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"

provider = get_provider(args.provider)
start = time.perf_counter()
result = provider.extract(path.read_bytes(), mime_type, EXTRACTION_PROMPT)
elapsed = time.perf_counter() - start

print(result.model_dump_json(indent=2))
print(f"\nProvider: {provider.name} | Time: {elapsed:.1f}s", file=sys.stderr)
