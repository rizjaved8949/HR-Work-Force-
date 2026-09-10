from pydantic import BaseModel

class VisualizationRequest(BaseModel):
    question: str
    data: list
