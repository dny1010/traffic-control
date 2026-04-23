from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, StreamingResponse

from ..service.floating_detector import FloatingDetector
from ..service.service import FloatingObjectService

router = APIRouter()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FLOATING_VIDEO_CANDIDATES = [
    PROJECT_ROOT / "floating_matters.mp4",
    PROJECT_ROOT / "floating_matter.mp4",
]

floating_object_service = FloatingObjectService()


@router.post("/detect")
async def detect_floating_object():
    result = floating_object_service.detect_floating_object()
    return {
        "event": "floating_object_detected",
        "details": result,
    }


@router.get("/video")
async def get_floating_video():
    for path in FLOATING_VIDEO_CANDIDATES:
        if path.exists():
            return FileResponse(path, media_type="video/mp4", filename=path.name)
    raise HTTPException(
        status_code=404,
        detail="floating_matters.mp4 또는 floating_matter.mp4 파일을 찾을 수 없습니다",
    )


@router.get("/stream")
async def get_floating_stream():
    try:
        detector = FloatingDetector(PROJECT_ROOT)
        source_video = detector.resolve_video()
        stream = detector.stream_detected_frames(source_video)
        return StreamingResponse(stream, media_type="multipart/x-mixed-replace; boundary=frame")
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(status_code=500, detail=f"부유물 스트림 생성 실패: {error}") from error
