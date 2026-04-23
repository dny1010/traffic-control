from fastapi import APIRouter
from ..service.service import TestFeatureService

router = APIRouter()
service = TestFeatureService()


@router.post("/video/upload")
async def upload_video():
    return service.upload_video()


@router.post("/video/analyze")
async def analyze_video():
    return service.run_ai_analysis()


@router.get("/result")
async def test_result():
    return service.get_test_result()