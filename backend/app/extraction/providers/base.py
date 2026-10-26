from abc import ABC, abstractmethod
from backend.app.schemas.extraction import DocumentExtraction
class ExtractionProvider(ABC):
    name: str
    @abstractmethod
    def extract(self, image_bytes: bytes, mime_type: str, prompt: str) -> DocumentExtraction: ...
