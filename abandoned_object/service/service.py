from pathlib import Path

from database.config import SessionLocal
from database.event_repository import create_event_with_detection
from .floating_detector import FloatingDetector


PROJECT_ROOT = Path(__file__).resolve().parents[2]
GENERATED_DIR = PROJECT_ROOT / "generated"
ANNOTATED_FLOATING_VIDEO_PATH = GENERATED_DIR / "floating_matter_annotated.mp4"


class AbandonedObjectService:
    def detect_floating_object(self, cctv_id: int = 1):
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
                "model_path": detected.model_path,
                "source_video": source_video_path.name,
                "confidence": detected.confidence,
                "boxes": detected.boxes,
                "frames_analyzed": detected.frames_analyzed,
                "annotated_video_url": "/abandoned-object/floating-video-annotated",
                "stream_url": "/abandoned-object/floating-stream",
                "duration_sec": duration_sec,
            }
        except Exception as e:
            db.rollback()
            return {"message": "Floating object detection failed", "error": str(e)}
        finally:
            db.close()

    def detect_abandoned_object(self, cctv_id: int = 1):
        db = SessionLocal()
        try:
            detection, event = create_event_with_detection(
                db=db,
                cctv_id=cctv_id,
                event_type="abandoned_object",
                description="5초 이상 정지된 부화물 감지",
                metadata={"duration_sec": 5, "source": "abandoned_object_service"},
                object_type="abandoned_object",
            )
            db.commit()
            return {
                "message": "Abandoned object detected and event created",
                "detection_id": detection.id,
                "event_id": event.id,
            }
        except Exception as e:
            db.rollback()
            return {"message": "Abandoned object detection failed", "error": str(e)}
        finally:
            db.close()