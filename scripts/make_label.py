import argparse
import mimetypes
import sys
from pathlib import Path

from backend.app.extraction.prompts import EXTRACTION_PROMPT
from backend.app.extraction.providers.factory import get_provider
from eval.label import EvalLabel

LABELS_DIR = Path("eval/dataset/labels")

parser = argparse.ArgumentParser(description="Create a draft label from a model's extraction")
parser.add_argument("image", help="Path to the bill image")
parser.add_argument("difficulty", choices=["easy", "medium", "hard", "edge"])
parser.add_argument("--provider", default="gemini", help="ollama or gemini (default: gemini)")
parser.add_argument("--force", action="store_true", help="Overwrite an existing label")
args = parser.parse_args()

image = Path(args.image)
if not image.exists():
    sys.exit(f"File not found: {image}")

out = LABELS_DIR / f"{image.stem}.json"
if out.exists() and not args.force:
    sys.exit(f"{out} already exists. It may contain your corrections. Use --force to overwrite.")

mime_type = mimetypes.guess_type(image)[0] or "image/jpeg"
result = get_provider(args.provider).extract(image.read_bytes(), mime_type, EXTRACTION_PROMPT)

LABELS_DIR.mkdir(parents=True, exist_ok=True)
label = EvalLabel(image=image.name, difficulty=args.difficulty, expected=result)
out.write_text(label.model_dump_json(indent=2), encoding="utf-8")
print(f"Draft saved: {out}. Now correct every field against the image.")
