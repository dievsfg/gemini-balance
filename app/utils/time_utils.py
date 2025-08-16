import datetime
import pytz
from typing import Any

def get_timezone(settings: Any) -> datetime.tzinfo:
    """获取配置中指定的时区对象"""
    try:
        return pytz.timezone(settings.TIMEZONE)
    except pytz.UnknownTimeZoneError:
        # 如果配置了无效的时区，则回退到 UTC
        return pytz.utc

def get_now(settings: Any) -> datetime.datetime:
    """获取带时区的当前时间"""
    return datetime.datetime.now(get_timezone(settings))