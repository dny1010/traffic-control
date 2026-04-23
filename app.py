from datetime import datetime
from itertools import count
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database.config import Base, engine, get_db
from models import CCTV, Detection, Device, Event
from fire.view.router import router as fire_router
from abandoned_object.view.router import router as abandoned_object_router
from traffic_jam.view.router import router as traffic_jam_router
from wrong_way.view.router import router as wrong_way_router
from emergency_vehicle.view.router import router as emergency_vehicle_router
from cctv_management.view.router import router as cctv_router
from event_management.view.router import router as event_router
from test_feature.view.router import router as test_router
from map_feature.view.router import router as map_router
from notification_feature.view.router import router as notification_router
from location_feature.view.router import router as location_router
from route_feature.view.router import router as route_router

app = FastAPI(title="Traffic Control System", description="교통 관제 시스템 API")
BASE_DIR = Path(__file__).resolve().parent


def _column_exists(inspector, table_name: str, column_name: str) -> bool:
    try:
        return any(col["name"] == column_name for col in inspector.get_columns(table_name))
    except Exception:
        return False


def _add_column_if_missing(table_name: str, column_name: str, definition_sql: str) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    if _column_exists(inspector, table_name, column_name):
        return
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}"))


def _make_cctv_fk_nullable(table_name: str) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return
    if not _column_exists(inspector, table_name, "cctv_id"):
        return

    dialect = engine.dialect.name
    with engine.begin() as conn:
        if dialect == "mysql":
            conn.execute(text(f"ALTER TABLE {table_name} MODIFY cctv_id INT NULL"))
        elif dialect == "postgresql":
            conn.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN cctv_id DROP NOT NULL"))


def ensure_runtime_schema() -> None:
    Base.metadata.create_all(bind=engine)

    _add_column_if_missing("event", "source_type", "VARCHAR(20) NULL")
    _add_column_if_missing("event", "device_id", "VARCHAR(50) NULL")
    _add_column_if_missing("event", "lat", "FLOAT NULL")
    _add_column_if_missing("event", "lng", "FLOAT NULL")
    _add_column_if_missing("event", "image_url", "TEXT NULL")

    _add_column_if_missing("detection", "source_type", "VARCHAR(20) NULL")
    _add_column_if_missing("detection", "device_id", "VARCHAR(50) NULL")

    _make_cctv_fk_nullable("event")
    _make_cctv_fk_nullable("detection")


@app.on_event("startup")
def init_db_tables():
    try:
        ensure_runtime_schema()
    except SQLAlchemyError as exc:
        # Keep API alive even when DB is temporarily unavailable.
        print(f"[WARN] DB initialization skipped: {exc}")


# Keep legacy routes for existing frontend compatibility.
app.include_router(fire_router, prefix="/fire", tags=["Fire Detection"])
app.include_router(abandoned_object_router, prefix="/abandoned-object", tags=["Abandoned Object Detection"])
app.include_router(traffic_jam_router, prefix="/traffic-jam", tags=["Traffic Jam Detection"])
app.include_router(wrong_way_router, prefix="/wrong-way", tags=["Wrong Way Detection"])
app.include_router(emergency_vehicle_router, prefix="/emergency-vehicle", tags=["Emergency Vehicle Detection"])
app.include_router(cctv_router, prefix="/cctvs", tags=["CCTV Management"])
app.include_router(event_router, prefix="/events", tags=["Event Management"])
app.include_router(test_router, prefix="/tests", tags=["Test Feature"])
app.include_router(map_router, prefix="/map", tags=["Map Feature"])
app.include_router(notification_router, prefix="/notifications", tags=["Notification Feature"])
app.include_router(location_router, prefix="/location", tags=["Location Feature"])
app.include_router(route_router, prefix="/routes", tags=["Route Feature"])


class EventCreateRequest(BaseModel):
    source_type: str = Field(default="device", description="cctv or device")
    cctv_id: int | None = None
    device_id: str | None = None
    event_type: str
    timestamp: datetime | None = None
    lat: float | None = None
    lng: float | None = None
    image_url: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None


class DetectionCreateRequest(BaseModel):
    source_type: str = Field(default="device", description="cctv or device")
    cctv_id: int | None = None
    device_id: str | None = None
    object_type: str
    detected_at: datetime | None = None


class DeviceRegisterRequest(BaseModel):
    device_id: str
    location: str | None = None
    status: str = "active"


class EventSocketManager:
    def __init__(self):
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = EventSocketManager()
test_id_counter = count(1)
test_results: dict[int, dict[str, Any]] = {}
pending_device_events: list[dict[str, Any]] = []


def serialize_event(row: Event) -> dict[str, Any]:
    return {
        "id": row.id,
        "source_type": row.source_type,
        "cctv_id": row.cctv_id,
        "device_id": row.device_id,
        "event_type": row.event_type,
        "timestamp": row.event_time.isoformat() if row.event_time else None,
        "lat": row.lat,
        "lng": row.lng,
        "image_url": row.image_url,
        "description": row.description,
        "metadata": row.event_metadata or {},
    }

@app.get("/")
async def root():
    return {"message": "Traffic Control System API"}


@app.get("/site")
async def site_view():
    return FileResponse(BASE_DIR / "frontend.html")


@app.get("/cctv")
def list_cctv(limit: int = Query(default=50, ge=1, le=500), db: Session = Depends(get_db)):
    rows = db.query(CCTV).order_by(CCTV.id.asc()).limit(limit).all()
    return {
        "items": [
            {
                "id": row.id,
                "location": row.location,
                "stream_url": row.stream_url,
                "direction": row.direction,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
            for row in rows
        ]
    }


@app.get("/cctv/{cctv_id}")
def cctv_detail(cctv_id: int, db: Session = Depends(get_db)):
    row = db.get(CCTV, cctv_id)
    if not row:
        raise HTTPException(status_code=404, detail="CCTV not found")
    return {
        "id": row.id,
        "location": row.location,
        "stream_url": row.stream_url,
        "direction": row.direction,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@app.get("/stream/{cctv_id}")
def cctv_stream(cctv_id: int, db: Session = Depends(get_db)):
    row = db.get(CCTV, cctv_id)
    if not row:
        raise HTTPException(status_code=404, detail="CCTV not found")
    if not row.stream_url:
        raise HTTPException(status_code=404, detail="Stream URL not configured")

    stream_url = row.stream_url.strip()
    if stream_url.startswith("http://") or stream_url.startswith("https://"):
        return RedirectResponse(url=stream_url)

    return {
        "cctv_id": row.id,
        "stream_url": stream_url,
        "message": "Use external RTSP/HTTP player to open this stream URL.",
    }


@app.post("/event")
async def create_event(payload: EventCreateRequest, db: Session = Depends(get_db)):
    if payload.source_type not in {"cctv", "device"}:
        raise HTTPException(status_code=400, detail="source_type must be 'cctv' or 'device'")

    if payload.source_type == "cctv" and payload.cctv_id is None:
        raise HTTPException(status_code=400, detail="cctv source requires cctv_id")
    if payload.source_type == "device" and not payload.device_id:
        raise HTTPException(status_code=400, detail="device source requires device_id")

    if payload.device_id:
        device = db.query(Device).filter(Device.device_id == payload.device_id).first()
        if not device:
            device = Device(device_id=payload.device_id, status="active")
            db.add(device)

    row = Event(
        source_type=payload.source_type,
        cctv_id=payload.cctv_id,
        device_id=payload.device_id,
        event_type=payload.event_type,
        event_time=payload.timestamp or datetime.now(),
        lat=payload.lat,
        lng=payload.lng,
        description=payload.description,
        image_url=payload.image_url,
        event_metadata=payload.metadata or {},
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    event_data = serialize_event(row)
    pending_device_events.insert(0, event_data)
    del pending_device_events[200:]

    await ws_manager.broadcast({"type": "event.created", "event": event_data})
    return event_data


@app.get("/event")
def list_event(
    type: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    query = db.query(Event)
    if type:
        query = query.filter(Event.event_type == type)

    rows = query.order_by(Event.event_time.desc()).limit(limit).all()
    return {"items": [serialize_event(row) for row in rows]}


@app.get("/event/recent")
def recent_event(db: Session = Depends(get_db)):
    row = db.query(Event).order_by(Event.event_time.desc()).first()
    if not row:
        return {"item": None}
    return {"item": serialize_event(row)}


@app.get("/event/{event_id}")
def event_detail(event_id: int, db: Session = Depends(get_db)):
    row = db.get(Event, event_id)
    if not row:
        raise HTTPException(status_code=404, detail="Event not found")
    return serialize_event(row)


@app.post("/detection")
def create_detection(payload: DetectionCreateRequest, db: Session = Depends(get_db)):
    if payload.source_type not in {"cctv", "device"}:
        raise HTTPException(status_code=400, detail="source_type must be 'cctv' or 'device'")

    row = Detection(
        source_type=payload.source_type,
        cctv_id=payload.cctv_id,
        device_id=payload.device_id,
        object_type=payload.object_type,
        detected_at=payload.detected_at or datetime.now(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "source_type": row.source_type,
        "cctv_id": row.cctv_id,
        "device_id": row.device_id,
        "object_type": row.object_type,
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
    }


@app.post("/test/upload")
async def upload_test_video(file: UploadFile = File(...)):
    payload = await file.read()
    test_id = next(test_id_counter)
    result = {
        "test_id": test_id,
        "filename": file.filename,
        "size_bytes": len(payload),
        "status": "uploaded",
        "summary": "Test video uploaded. Analysis result is pending.",
    }
    test_results[test_id] = result
    return result


@app.get("/test/result/{test_id}")
def get_test_result(test_id: int):
    result = test_results.get(test_id)
    if not result:
        raise HTTPException(status_code=404, detail="Test result not found")
    return result


@app.post("/device/register")
def register_device(payload: DeviceRegisterRequest, db: Session = Depends(get_db)):
    row = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if row:
        row.location = payload.location
        row.status = payload.status
    else:
        row = Device(
            device_id=payload.device_id,
            location=payload.location,
            status=payload.status,
        )
        db.add(row)

    db.commit()
    db.refresh(row)
    return {
        "id": row.id,
        "device_id": row.device_id,
        "location": row.location,
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@app.get("/device/event")
def poll_device_events(limit: int = Query(default=20, ge=1, le=200)):
    return {"items": pending_device_events[:limit]}


@app.websocket("/ws/event")
async def event_websocket(websocket: WebSocket):
    await ws_manager.connect(websocket)
    try:
        await websocket.send_json({"type": "system", "message": "connected"})
        while True:
            # Keep alive and ignore client payloads.
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
    except Exception:
        ws_manager.disconnect(websocket)