from fastapi import APIRouter
from .schemas import VisualizationRequest
from .service import create_visualization

router = APIRouter()

@router.post('/generate')
def generate(request: VisualizationRequest):
    return create_visualization(request.question, request.data)
