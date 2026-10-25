from typing import Literal
from pydantic import BaseModel
from backend.app.schemas.extraction import DocumentExtraction

class EvalLabel(BaseModel):
    image:str
    difficulty:Literal["easy","medium","hard","edge"]
    notes:str=""
    expected:DocumentExtraction