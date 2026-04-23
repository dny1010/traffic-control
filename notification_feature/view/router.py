from fastapi import APIRouter
from ..service.service import NotificationFeatureService

router = APIRouter()
service = NotificationFeatureService()


@router.get("/realtime")
async def realtime_receive():
    return service.realtime_receive()


@router.post("/push")
async def push_notify():
    return service.push_notify()


@router.get("/")
async def list_notifications():
    return service.list_notifications()