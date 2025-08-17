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
    prefix="/api",
    tags=["stats"],
    dependencies=[Depends(verify_token)]
)

stats_service = StatsService()

@router.get("/stats/model-usage",
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

@router.get("/key-usage-details/{key}",
            summary="获取指定密钥最近24小时的模型调用次数",
            description="根据提供的 API 密钥，返回过去24小时内每个模型被调用的次数统计。")
async def get_key_usage_details(key: str, period: str = "24h"):
    """
    Retrieves the model usage statistics for a specific API key within the specified period.

    Args:
        key: The API key to get usage details for.
        period: The time period ('24h' or 'today').

    Returns:
        A dictionary with model names as keys and their usage data as values.
        Example: {"gemini-pro": {"call_count": 10, "total_prompt_tokens": 100, "total_candidates_tokens": 200}}

    Raises:
        HTTPException: If an error occurs during data retrieval.
    """
    try:
        if period not in ["24h", "today"]:
            raise HTTPException(status_code=400, detail="Invalid period specified. Use '24h' or 'today'.")
            
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