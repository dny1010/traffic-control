from fastapi import APIRouter
from ..service.service import RouteFeatureService

router = APIRouter()
service = RouteFeatureService()


@router.get("/search")
async def search_route(origin: str, destination: str):
    return service.search_route(origin=origin, destination=destination)


@router.get("/guidance/{route_id}")
async def map_guidance(route_id: str):
    return service.map_guidance(route_id=route_id)