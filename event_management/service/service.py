from database.config import SessionLocal
from database.event_repository import create_event_with_detection
from models import Event


class EventManagementService:
    def receive_event(self, payload: dict):
        db = SessionLocal()
        try:
            cctv_id = int(payload.get("cctv_id", 1))
            event_type = payload.get("event_type", "unknown_event")
            description = payload.get("description", f"{event_type} 수신")
            metadata = payload.get("metadata", {})
            object_type = payload.get("object_type", event_type)

            detection, event = create_event_with_detection(
                db=db,
                cctv_id=cctv_id,
                event_type=event_type,
                description=description,
                metadata=metadata,
                object_type=object_type,
            )
            db.commit()
            return {
                "message": "이벤트 수신 및 저장 완료",
                "payload": payload,
                "detection_id": detection.id,
                "event_id": event.id,
            }
        except Exception as e:
            db.rollback()
            return {"message": "이벤트 저장 실패", "error": str(e), "payload": payload}
        finally:
            db.close()

    def list_events(self, event_type: str | None = None, sort: str = "desc"):
        db = SessionLocal()
        try:
            query = db.query(Event)
            if event_type:
                query = query.filter(Event.event_type == event_type)

            order_by = Event.event_time.desc() if sort == "desc" else Event.event_time.asc()
            rows = query.order_by(order_by).limit(100).all()

            items = [
                {
                    "id": row.id,
                    "cctv_id": row.cctv_id,
                    "event_type": row.event_type,
                    "event_time": row.event_time.isoformat() if row.event_time else None,
                    "description": row.description,
                }
                for row in rows
            ]
            return {
                "message": "이벤트 목록 조회 완료",
                "event_type": event_type,
                "sort": sort,
                "items": items,
            }
        finally:
            db.close()

    def get_event_detail(self, event_id: int):
        db = SessionLocal()
        try:
            row = db.get(Event, event_id)
            if not row:
                return {"message": "이벤트를 찾을 수 없음", "event_id": event_id}
            return {
                "message": "이벤트 상세 조회 완료",
                "id": row.id,
                "cctv_id": row.cctv_id,
                "event_type": row.event_type,
                "event_time": row.event_time.isoformat() if row.event_time else None,
                "description": row.description,
                "metadata": row.event_metadata or {},
            }
        finally:
            db.close()

    def get_event_metadata(self, event_id: int):
        db = SessionLocal()
        try:
            row = db.get(Event, event_id)
            if not row:
                return {"message": "이벤트를 찾을 수 없음", "event_id": event_id}
            return {
                "message": "이벤트 metadata 조회 완료",
                "event_id": event_id,
                "metadata": row.event_metadata or {},
            }
        finally:
            db.close()