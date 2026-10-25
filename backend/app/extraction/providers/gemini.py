import os
import sys
import time

from dotenv import load_dotenv
from google import genai
from google.genai import errors, types

from backend.app.extraction.providers.base import ExtractionProvider
from backend.app.schemas.extraction import DocumentExtraction

load_dotenv()

RETRY_WAITS = [5, 15, 30]  # seconds to wait before each retry when Gemini is busy


class GeminiProvider(ExtractionProvider):
    name = "gemini"

    def __init__(self, model: str | None = None):
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")

    def extract(self, image_bytes: bytes, mime_type: str, prompt: str) -> DocumentExtraction:
        for attempt in range(len(RETRY_WAITS) + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), prompt],
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=DocumentExtraction,
                        temperature=0,
                    ),
                )
                return DocumentExtraction.model_validate_json(response.text)
            except errors.ServerError:
                if attempt == len(RETRY_WAITS):
                    raise
                # stderr, not stdout: the MCP server uses stdout for its protocol.
                print(f"Gemini busy, retrying in {RETRY_WAITS[attempt]}s...", file=sys.stderr)
                time.sleep(RETRY_WAITS[attempt])
