from fastapi import APIRouter, HTTPException
from ..service.service import FireDetectionService

router = APIRouter()

fire_service = FireDetectionService()

@router.post("/detect")
async def detect_fire():
    # 화재 감지 로직 호출
    result = fire_service.detect_fire()
    return {"event": "fire_detected", "details": result}