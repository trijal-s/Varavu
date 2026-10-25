"""Run a provider over every labeled bill and print accuracy.

Usage:
    python -m eval.run_eval --provider gemini
    python -m eval.run_eval --provider gemini --cached   # reuse saved outputs, no API calls
"""
import argparse
import json
import mimetypes
import time
from collections import Counter, defaultdict
from pathlib import Path

from backend.app.extraction.cleanup import clean_document
from backend.app.schemas.extraction import DocumentExtraction
from eval.compare import BOTH_EMPTY, CORRECT, INVENTED, MISSED, WRONG, compare_document
from eval.label import EvalLabel

DATASET = Path("eval/dataset")
RESULTS = Path("eval/results")

# The fields that matter most for the accounts. Reported separately so they aren't
# hidden among the many line-item details.
KEY_FIELDS = ["document_type", "vendor_name", "bill_number", "date_as_written", "total",
              "item.description", "item.quantity", "item.amount"]


def get_prediction(label: EvalLabel, provider_name: str, cached: bool) -> tuple[DocumentExtraction, float]:
    """Return the model's output for one bill, from the saved file or a fresh model call."""
    cache_file = RESULTS / provider_name / f"{Path(label.image).stem}.json"
    if cached and cache_file.exists():
        return DocumentExtraction.model_validate_json(cache_file.read_text(encoding="utf-8")), 0.0

    from backend.app.extraction.prompts import EXTRACTION_PROMPT
    from backend.app.extraction.providers.factory import get_provider

    image = DATASET / "private" / label.image
    mime_type = mimetypes.guess_type(image)[0] or "image/jpeg"
    start = time.perf_counter()
    prediction = get_provider(provider_name).extract(image.read_bytes(), mime_type, EXTRACTION_PROMPT)
    elapsed = time.perf_counter() - start

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(prediction.model_dump_json(indent=2), encoding="utf-8")
    return prediction, elapsed


def accuracy(counts: Counter) -> float:
    total = sum(counts.values())
    return (counts[CORRECT] + counts[BOTH_EMPTY]) / total * 100 if total else 0.0


def summary_line(name: str, counts: Counter) -> str:
    return (f"{name:<22} acc {accuracy(counts):5.1f}%   correct {counts[CORRECT]:>3}  wrong {counts[WRONG]:>3}  "
            f"missed {counts[MISSED]:>3}  invented {counts[INVENTED]:>3}")


def main():
    parser = argparse.ArgumentParser(description="Evaluate extraction against labels")
    parser.add_argument("--provider", default="gemini", help="ollama or gemini")
    parser.add_argument("--cached", action="store_true", help="Reuse saved outputs instead of calling the model")
    parser.add_argument("--raw", action="store_true", help="Score the model output without clean-up")
    args = parser.parse_args()

    overall, by_field, by_difficulty = Counter(), defaultdict(Counter), defaultdict(Counter)
    times = []

    for label_file in sorted((DATASET / "labels").glob("*.json")):
        label = EvalLabel.model_validate_json(label_file.read_text(encoding="utf-8"))
        try:
            prediction, elapsed = get_prediction(label, args.provider, args.cached)
        except Exception as error:  # one failing bill shouldn't stop the whole run
            print(f"ERROR  {label.image}: {error}")
            continue
        if elapsed:
            times.append(elapsed)
        if not args.raw:
            prediction = clean_document(prediction)

        bill_counts = Counter()
        for field, outcomes in compare_document(label.expected, prediction).items():
            by_field[field].update(outcomes)
            bill_counts.update(outcomes)
        overall.update(bill_counts)
        by_difficulty[label.difficulty].update(bill_counts)
        print(summary_line(label.image, bill_counts))

    print("\n=== By difficulty ===")
    for difficulty in ("easy", "medium", "hard", "edge"):
        if difficulty in by_difficulty:
            print(summary_line(difficulty, by_difficulty[difficulty]))

    print("\n=== Weakest fields ===")
    for field, counts in sorted(by_field.items(), key=lambda item: accuracy(item[1]))[:10]:
        print(summary_line(field, counts))

    key = Counter()
    for field in KEY_FIELDS:
        key.update(by_field.get(field, Counter()))

    print(f"\n=== Overall ({args.provider}) ===")
    print(summary_line("key fields", key))
    print(summary_line("all fields", overall))
    if times:
        print(f"Average time per bill: {sum(times) / len(times):.1f}s")

    summary = {"provider": args.provider, "cleanup": not args.raw, "key_field_accuracy": round(accuracy(key), 1),
               "accuracy": round(accuracy(overall), 1), "counts": dict(overall),
               "by_difficulty": {d: round(accuracy(c), 1) for d, c in by_difficulty.items()}}
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / f"summary_{args.provider}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
