"""
routes — FastAPI routers for the API service.

Exposes:
    - router : main APIRouter with all endpoints
"""
from .simulation import router

__all__ = ["router"]
