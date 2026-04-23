from fastapi import APIRouter, Body, HTTPException

from ..service.service import EmergencyVehicleService

# 이 router 는 emergency_vehicle 기능 전용 API 출입문입니다.
# 실제 분석은 service 가 담당하고, router 는 요청을 전달하고 결과를 돌려주는 역할만 합니다.
router = APIRouter()

# 서비스 객체는 요청마다 새로 만들 필요가 없어서
# 모듈 로드 시 한 번만 생성해 재사용합니다.
emergency_vehicle_service = EmergencyVehicleService()


@router.post("/detect")
async def detect_emergency_vehicle(payload: dict | None = Body(default=None)):
    """
    긴급출동 차량 후속 판단 API 입니다.

    흐름:
    1. 상위 탐지 모듈이 긴급출동 차량 후보 좌표를 전달
    2. router 가 payload 를 service 로 전달
    3. service 가 이동 방향, 차선, 주변 차량 정보를 계산
    4. 결과를 API 응답으로 반환

    즉, 이 파일은 계산 담당이 아니라 "입구" 역할입니다.
    """
    result = emergency_vehicle_service.detect_emergency_vehicle(payload)

    # 입력값이 부족하면 service 가 ok=False 를 반환하므로,
    # API 레벨에서는 400 에러로 바꿔서 호출한 쪽이 바로 문제를 알 수 있게 합니다.
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)

    # event 이름을 같이 돌려주는 이유는
    # 나중에 여러 이벤트 타입을 하나의 공통 형식으로 처리하기 쉽게 하기 위해서입니다.
    return {
        "event": "emergency_vehicle_detected",
        "details": result,
    }
