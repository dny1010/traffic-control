from fastapi import APIRouter, HTTPException
from ..service.service import WrongWayService

router = APIRouter()

@router.post("/detect")
async def detect_wrong_way():
    wrong_way_service = WrongWayService()
    result = wrong_way_service.detect_wrong_way()

    if not result.get("ok", False):
        raise HTTPException(status_code=400, detail=result)

    return {
        "event": "wrong_way_detected",
        "details": result,
    }

    # router.py 의 역할:
    # 1. HTTP 요청을 받기
    # 2. service 호출하기
    # 3. 결과에 따라 적절한 응답 코드 반환하기
    #
    # 이유:
    # 라우터가 분석 로직까지 모두 알게 되면 파일 역할이 섞기기 때문에
    # 라우터는 "입구", 서비스는 "실제 처리"만 담당하도록 나눔