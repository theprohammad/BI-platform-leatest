from pydantic import BaseModel
from typing import Any


class AnalysisResponse(BaseModel):
    success: bool
    message: str
    data: Any