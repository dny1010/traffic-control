from pathlib import Path

from database.config import SessionLocal
from database.event_repository import create_event_with_detection

from .floating_detector import FloatingDetector


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class FloatingObjectService:
    """부유물(실시간 모델 추론) 전용 서비스."""

    def detect_floating_object(self, cctv_id: int = 1) -> dict:
        db = SessionLocal()
        try:
            detector = FloatingDetector(PROJECT_ROOT)
            source_video_path = detector.resolve_video()
            detected = detector.detect(source_video_path)
            duration_sec = detector.get_video_duration(source_video_path)

            detection, event = create_event_with_detection(
                db=db,
                cctv_id=cctv_id,
                event_type="floating_object",
                description="도로 위 부유물 감지",
                metadata={
                    "source": "floating_object_service",
                    "model": detected.model_name,
                    "confidence": detected.confidence,
                    "boxes": detected.boxes,
                    "frames_analyzed": detected.frames_analyzed,
                },
                object_type="floating_object",
            )
            db.commit()

            return {
                "message": "Floating object detected and event created",
                "detection_id": detection.id,
                "event_id": event.id,
                "model": detected.model_name,
                "confidence": detected.confidence,
                "boxes": detected.boxes,
                "frames_analyzed": detected.frames_analyzed,
                "stream_url": "/floating-object/stream",
                "duration_sec": duration_sec,
            }
        except Exception as error:
            db.rollback()
            return {
                "message": "Floating object detection failed",
                "error": str(error),
            }
        finally:
            db.close()
