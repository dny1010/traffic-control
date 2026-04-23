from database.config import SessionLocal
from database.event_repository import create_event_with_detection


class EmergencyVehicleService:
    def detect_emergency_vehicle(self, cctv_id: int = 1):
        db = SessionLocal()
        try:
            detection, event = create_event_with_detection(
                db=db,
                cctv_id=cctv_id,
                event_type="emergency_vehicle",
                description="긴급출동 차량(구급/경찰) 감지",
                metadata={"source": "emergency_vehicle_service"},
                object_type="emergency_vehicle",
            )
            db.commit()
            return {
                "message": "Emergency vehicle detected and event created",
                "detection_id": detection.id,
                "event_id": event.id,
            }
        except Exception as e:
            db.rollback()
            return {"message": "Emergency vehicle detection failed", "error": str(e)}
        finally:
            db.close()