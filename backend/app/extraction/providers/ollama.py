import os
import ollama
from dotenv import load_dotenv
from .base import ExtractionProvider
from backend.app.schemas.extraction import DocumentExtraction

load_dotenv()

class OllamaProvider(ExtractionProvider):
    name= "ollama"
    def __init__(self,model:str | None=None):
        self.client = ollama.Client(os.getenv("OLLAMA_HOST", "http://localhost:11434"))
        self.model = os.getenv("OLLAMA_MODEL", model)
    def extract(self,image_bytes:bytes,mime_type:str,prompt:str)->DocumentExtraction:
        response = self.client.chat(
            model=self.model,
            messages=[{"role":"user","content":prompt,"images":[image_bytes]}],
            format=DocumentExtraction.model_json_schema(),
            options={"temperature":0,"num_ctx": 8192}       
        )
        return DocumentExtraction.model_validate_json(response.message.content)