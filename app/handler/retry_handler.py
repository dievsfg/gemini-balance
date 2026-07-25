
from functools import wraps
from typing import Callable, TypeVar

from app.config.config import settings
from app.log.logger import get_retry_logger
from app.utils.helpers import redact_key_for_logging

T = TypeVar("T")
logger = get_retry_logger()


class RetryHandler:
    """重试处理装饰器"""

    def __init__(self, key_arg: str = "api_key"):
        self.key_arg = key_arg

    def __call__(self, func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(settings.MAX_RETRIES):
                retries = attempt + 1
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    logger.warning(
                        f"API call failed with error: {str(e)}. Attempt {retries} of {settings.MAX_RETRIES}"
                    )

                    # 从函数参数中获取 key_manager
                    key_manager = kwargs.get("key_manager")
                    if key_manager:
                        old_key = kwargs.get(self.key_arg)
                        model_name = kwargs.get("model") or kwargs.get("model_name")
                        if not model_name and "request" in kwargs:
                            req_obj = kwargs["request"]
                            if hasattr(req_obj, "model") and getattr(req_obj, "model", None):
                                model_name = req_obj.model
                            elif hasattr(req_obj, "model_name") and getattr(req_obj, "model_name", None):
                                model_name = req_obj.model_name
                        status_code = getattr(e, "status_code", None) or (
                            e.args[0] if e.args and isinstance(e.args[0], int) else None
                        )
                        error_msg = str(e)
                        new_key = await key_manager.handle_api_failure(
                            old_key,
                            retries,
                            model_name=model_name,
                            status_code=status_code,
                            error_msg=error_msg,
                        )
                        if new_key:
                            kwargs[self.key_arg] = new_key
                            logger.info(f"Switched to new API key: {redact_key_for_logging(new_key)}")
                        else:
                            logger.error(f"No valid API key available after {retries} retries.")
                            break

            logger.error(
                f"All retry attempts failed, raising final exception: {str(last_exception)}"
            )
            raise last_exception

        return wrapper
