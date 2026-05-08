from fastapi import APIRouter
from app.api.v1 import analyze, video, followup, debug, demo, validate_photo

router = APIRouter(prefix="/api/v1")
router.include_router(analyze.router, tags=["Analysis"])
router.include_router(video.router, tags=["Video"])
router.include_router(followup.router, tags=["Followup"])
router.include_router(validate_photo.router, tags=["Validation"])
router.include_router(debug.router)
router.include_router(demo.router)
