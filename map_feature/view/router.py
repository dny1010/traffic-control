from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from ..service.service import MapFeatureService

router = APIRouter()
service = MapFeatureService()


@router.get("/base")
async def base_map():
    return service.base_map()


@router.get("/events/markers")
async def event_markers():
    return service.event_markers()


@router.get("/events/{event_id}")
async def marker_event_detail(event_id: int):
    return service.event_detail(event_id)


@router.get("/main")
async def map_main():
    return RedirectResponse(url="/application")