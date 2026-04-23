from fastapi import APIRouter, HTTPException
from ..service.service import EmergencyVehicleService

router = APIRouter()

emergency_vehicle_service = EmergencyVehicleService()

@router.post("/detect")
async def detect_emergency_vehicle():
    # 긴급출동 감지 로직 호출
    result = emergency_vehicle_service.detect_emergency_vehicle()
    return {"event": "emergency_vehicle_detected", "details": result}