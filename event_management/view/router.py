from fastapi import APIRouter, WebSocket
from ..service.service import EventManagementService

router = APIRouter()
service = EventManagementService()


@router.post("/ingest")
async def receive_event(payload: dict):
    return service.receive_event(payload)


@router.get("/")
async def list_events(event_type: str | None = None, sort: str = "desc"):
    return service.list_events(event_type=event_type, sort=sort)


@router.get("/{event_id}")
async def event_detail(event_id: int):
    return service.get_event_detail(event_id)


@router.get("/{event_id}/metadata")
async def event_metadata(event_id: int):
    return service.get_event_metadata(event_id)


@router.websocket("/ws")
async def event_realtime_ws(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"message": "실시간 이벤트 표시 구조 준비 완료"})
    await websocket.close()