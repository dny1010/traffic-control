from fastapi import APIRouter, HTTPException
from ..service.service import WrongWayService

router = APIRouter()

wrong_way_service = WrongWayService()

@router.post("/detect")
async def detect_wrong_way():
    # 역주행 감지 로직 호출
    result = wrong_way_service.detect_wrong_way()
    return {"event": "wrong_way_detected", "details": result}