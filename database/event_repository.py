from datetime import datetime
from sqlalchemy.orm import Session

from models import CCTV, Detection, Event


def ensure_cctv_exists(
    db: Session,
    cctv_id: int,
    location: str | None = None,
    stream_url: str | None = None,
    direction: str | None = None,
) -> CCTV:
    cctv = db.get(CCTV, cctv_id)
    if cctv is None:
        cctv = CCTV(
            id=cctv_id,
            location=location or f"CCTV-{cctv_id}",
            stream_url=stream_url or "about:blank",
            direction=(direction or "N/A")[:10],
        )
        db.add(cctv)
        db.flush()
        return cctv

    if location and cctv.location != location:
        cctv.location = location
    if stream_url and cctv.stream_url != stream_url:
        cctv.stream_url = stream_url
    if direction and cctv.direction != direction[:10]:
        cctv.direction = direction[:10]
    db.flush()
    return cctv


def create_event_with_detection(
    db: Session,
    cctv_id: int,
    event_type: str,
    description: str,
    metadata: dict | None = None,
    object_type: str | None = None,
) -> tuple[Detection, Event]:
    ensure_cctv_exists(db, cctv_id)

    detection = Detection(
        cctv_id=cctv_id,
        object_type=object_type or event_type,
        detected_at=datetime.now(),
    )
    db.add(detection)
    db.flush()

    event = Event(
        cctv_id=cctv_id,
        event_type=event_type,
        event_time=datetime.now(),
        description=description,
        event_metadata=metadata or {},
    )
    db.add(event)
    db.flush()

    return detection, event