from fastapi import APIRouter, HTTPException
from ..service.service import CctvManagementService

router = APIRouter()
service = CctvManagementService()


@router.get("/")
async def list_cctvs(
    region: str | None = None,
    limit: int | None = None,
    min_x: float | None = None,
    max_x: float | None = None,
    min_y: float | None = None,
    max_y: float | None = None,
):
    result = service.list_cctvs(
        region=region,
        limit=limit,
        min_x=min_x,
        max_x=max_x,
        min_y=min_y,
        max_y=max_y,
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=result.get("message"))
    return result


@router.get("/{cctv_id}")
async def cctv_detail(cctv_id: int):
    result = service.get_cctv_detail(cctv_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result


@router.get("/{cctv_id}/stream")
async def cctv_stream(cctv_id: int):
    result = service.get_stream_url(cctv_id)
    if not result.get("ok"):
        raise HTTPException(status_code=404, detail=result.get("message"))
    return result