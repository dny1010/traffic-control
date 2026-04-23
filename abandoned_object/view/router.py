from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from ..service.floating_detector import FloatingDetector
from ..service.service import AbandonedObjectService

# 이 router 객체는 abandoned_object 기능의 URL 묶음입니다.
# 쉽게 말해 "낙하물 기능 전용 출입문"이라고 보면 됩니다.
router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLOATING_VIDEO_CANDIDATES = [
    PROJECT_ROOT / "floating_matters.mp4",
    PROJECT_ROOT / "floating_matter.mp4",
]
ANNOTATED_FLOATING_VIDEO_PATH = PROJECT_ROOT / "generated" / "floating_matter_annotated.mp4"

abandoned_object_service = AbandonedObjectService()


@router.post("/detect-floating")
async def detect_floating_object():
    result = abandoned_object_service.detect_floating_object()
    return {"event": "floating_object_detected", "details": result}


@router.get("/floating-video")
async def get_floating_video():
    for path in FLOATING_VIDEO_CANDIDATES:
        if path.exists():
            return FileResponse(path, media_type="video/mp4", filename=path.name)
    raise HTTPException(status_code=404, detail="floating_matters.mp4 또는 floating_matter.mp4 파일을 찾을 수 없습니다")


@router.get("/floating-video-annotated")
async def get_annotated_floating_video():
    if not ANNOTATED_FLOATING_VIDEO_PATH.exists():
        raise HTTPException(status_code=404, detail="박스 처리된 부유물 영상이 아직 생성되지 않았습니다")
    return FileResponse(ANNOTATED_FLOATING_VIDEO_PATH, media_type="video/mp4", filename=ANNOTATED_FLOATING_VIDEO_PATH.name)


@router.get("/floating-stream")
async def get_floating_stream():
    detector = FloatingDetector(PROJECT_ROOT)
    source_video = detector.resolve_video()
    stream = detector.stream_detected_frames(source_video)
    return StreamingResponse(stream, media_type="multipart/x-mixed-replace; boundary=frame")

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
