from fastapi import APIRouter, HTTPException
from ..service.service import FireDetectionService

router = APIRouter()

fire_service = FireDetectionService()


@router.post("/detect")
async def detect_fire():
    # / 라우터는 HTTP 요청과 응답을 담당합니다.
    # / 실제 분석은 서비스에 맡기고, 성공/실패 응답 형태는 여기서 정리합니다.
    result = fire_service.detect_fire()

    # / 분석 실패라면 API 호출자에게 실패 상태를 분명하게 알려줍니다.
    if not result.get("ok", False):
        raise HTTPException(
            status_code=400,
            detail=result,
        )

    # / 성공 응답의 바깥 형태는 라우터에서 조합합니다.
    return {
        "event": fire_service.getResponseEventName(),
        "details": result,
    }
