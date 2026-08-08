from pydantic import BaseModel, HttpUrl


class AnalysisRequest(BaseModel):
    company_name: str
    website: HttpUrl
    industry: str
    target_market: str