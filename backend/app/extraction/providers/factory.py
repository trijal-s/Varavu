import os

from dotenv import load_dotenv

from backend.app.extraction.providers.base import ExtractionProvider

load_dotenv()


def get_provider(name: str | None = None) -> ExtractionProvider:
    """Return the extraction provider by name, or the one set in .env."""
    name = (name or os.getenv("EXTRACTION_PROVIDER", "ollama")).lower()

    # Imports are inside each branch so you only need the library you actually use.
    if name == "ollama":
        from backend.app.extraction.providers.ollama import OllamaProvider
        return OllamaProvider()
    if name == "gemini":
        from backend.app.extraction.providers.gemini import GeminiProvider
        return GeminiProvider()

    raise ValueError(f"Unknown provider '{name}'. Use 'ollama' or 'gemini'.")
