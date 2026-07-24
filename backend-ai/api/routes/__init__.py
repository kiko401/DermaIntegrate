"""API 路由子模块。"""

from .system import router as system_router
from .tasks import router as tasks_router
from .stream import router as stream_router
from .features import router as features_router

__all__ = ["system_router", "tasks_router", "stream_router", "features_router"]
