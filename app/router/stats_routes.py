from fastapi import APIRouter, Depends, HTTPException, Request
from starlette import status
from app.core.security import verify_auth_token
from app.service.stats.stats_service import StatsService
from app.log.logger import get_stats_logger
from app.utils.helpers import redact_key_for_logging

logger = get_stats_logger()


async def verify_token(request: Request):
    auth_token = request.cookies.get("auth_token")
    if not auth_token or not verify_auth_token(auth_token):
        logger.warning("Unauthorized access attempt to scheduler API")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

router = APIRouter(
    prefix="/api/stats",
    tags=["stats"],
    dependencies=[Depends(verify_token)]
)

stats_service = StatsService()

@router.get("/model-usage",
            summary="获取各模型在指定时间段内的调用统计信息",
            description="返回指定时间段内（'1m', '1h', '24h', 'today'）每个模型的使用次数和Token消耗。")
async def get_model_usage_stats(period: str):
    """
    Retrieves model usage statistics for a specified period.

    Args:
        period: The time period ('1m', '1h', '24h', 'today').

    Returns:
        A list of dictionaries with model usage stats.
    """
    try:
        if period not in ["1m", "1h", "24h", "today"]:
            raise HTTPException(status_code=400, detail="Invalid period specified.")
        
        model_stats = await stats_service.get_model_usage_stats(period)
        return model_stats
    except ValueError as e:
        logger.error(f"Invalid period provided for model usage stats: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching model usage stats for period {period}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取模型使用统计时出错: {e}"
        )

@router.get("/key-details",
            summary="获取指定密钥在指定时间段内的调用详情",
            description="根据提供的 API 密钥和时间段，返回该密钥的详细调用记录。")
async def get_key_call_details(key: str, period: str):
    try:
        if period not in ["today", "1h", "8h", "24h"]:
            raise HTTPException(status_code=400, detail="Invalid period specified.")
        details = await stats_service.get_key_call_details(key, period)
        return details
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching key call details for key {redact_key_for_logging(key)}: {e}")
        raise HTTPException(status_code=500, detail="Error fetching key call details.")

@router.get("/key-model-usage",
            summary="获取指定密钥在指定时间段内的模型使用统计",
            description="根据提供的 API 密钥和时间段，返回该密钥下每个模型的使用统计（调用次数、Token数）。")
async def get_key_model_usage(key: str, period: str):
    try:
        if period not in ["today", "1h", "8h", "24h"]:
            raise HTTPException(status_code=400, detail="Invalid period specified. Use 'today', '1h', '8h' or '24h'.")
        usage_details = await stats_service.get_key_usage_details(key, period)
        return usage_details
    except ValueError as e:
        logger.error(f"Invalid period provided for key usage details: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error fetching key usage details for key {redact_key_for_logging(key)}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取密钥使用详情时出错: {e}"
        )