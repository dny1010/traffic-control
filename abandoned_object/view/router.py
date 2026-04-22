from fastapi import APIRouter, Body, HTTPException

from ..service.service import AbandonedObjectService

# 이 router 객체는 abandoned_object 기능의 URL 묶음입니다.
# 쉽게 말해 "낙하물 기능 전용 출입문"이라고 보면 됩니다.
router = APIRouter()

# 서비스 객체는 요청이 올 때마다 새로 만들 필요가 없어서
# 모듈이 로드될 때 한 번만 생성해 재사용합니다.
abandoned_object_service = AbandonedObjectService()


@router.post("/detect")
async def detect_abandoned_object(payload: dict | None = Body(default=None)):
    """
    낙하물 감지 후속 판단 API 입니다.

    흐름:
    1. 상위 탐지 모듈 또는 모델 추론 코드가 box 탐지 결과를 보냄
    2. router 는 그 payload 를 service 로 전달
    3. service 는 낙하물 여부를 판단
    4. 결과를 다시 API 응답으로 반환

    즉, router 는 직접 판단하지 않고
    "요청을 받아 service 에 넘기고 결과를 돌려주는 입구" 역할만 합니다.
    """
    result = abandoned_object_service.detect_abandoned_object(payload)

    # 입력 형식이 잘못되었거나 box 클래스가 아닌 경우에는
    # 클라이언트가 바로 원인을 알 수 있도록 400 에러로 반환합니다.
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result)

    # event 키를 같이 주는 이유:
    # 나중에 프론트나 다른 모듈이 여러 이벤트 타입을 공통 형식으로 처리할 때
    # 어떤 기능의 응답인지 쉽게 구분할 수 있게 하기 위함입니다.
    return {
        "event": "abandoned_object_detected",
        "details": result,
    }
