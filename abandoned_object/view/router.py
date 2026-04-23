from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from ..service.floating_detector import FloatingDetector
from ..service.service import AbandonedObjectService

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
async def detect_abandoned_object():
    # 부화물 감지 로직 호출
    result = abandoned_object_service.detect_abandoned_object()
    return {"event": "abandoned_object_detected", "details": result}