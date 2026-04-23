from fastapi import APIRouter
from ..service.service import LocationFeatureService

router = APIRouter()
service = LocationFeatureService()


@router.get("/current")
async def current_location():
    return service.current_location()


@router.get("/nearby-events")
async def nearby_events(distance_km: float = 3.0):
    return service.nearby_events(distance_km=distance_km)