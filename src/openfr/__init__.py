"""
OpenFR - Financial Research Agent based on AKShare
"""

import os
import sys
import types
import warnings

__version__ = "0.1.0"

# 禁用 tqdm 进度条（AKShare 内部使用）
os.environ["TQDM_DISABLE"] = "1"
os.environ["TQDM_MONITOR_INTERVAL"] = "0"

# 默认禁用 py_mini_racer/native V8。部分 AKShare/同花顺路径会在 macOS 上触发
# libmini_racer address_pool_manager fatal，进程会直接 trace trap，无法 try/except 捕获。
if (
    os.getenv("OPENFR_ENABLE_MINI_RACER", "0") != "1"
    and os.getenv("OPENFR_ENABLE_THS_JS", "0") != "1"
):
    class _DisabledMiniRacerContext:
        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "py_mini_racer is disabled by OpenFR runtime safety. "
                "Set OPENFR_ENABLE_MINI_RACER=1 only if this environment is known stable."
            )

    class _DisabledMiniRacer(types.ModuleType):
        def __getattr__(self, name: str):
            if name in {"MiniRacer", "StrictMiniRacer", "mini_racer"}:
                return _DisabledMiniRacerContext
            raise AttributeError(name)

    _disabled_mini_racer = _DisabledMiniRacer("py_mini_racer")
    _disabled_mini_racer.MiniRacer = _DisabledMiniRacerContext
    _disabled_mini_racer.StrictMiniRacer = _DisabledMiniRacerContext
    _disabled_mini_racer.mini_racer = _DisabledMiniRacerContext
    sys.modules.setdefault("py_mini_racer", _disabled_mini_racer)
    sys.modules.setdefault("py_mini_racer.py_mini_racer", _disabled_mini_racer)

# 禁用不必要的警告
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

from openfr.config import Config
from openfr.graph import ResearchGraph

__all__ = ["ResearchGraph", "Config", "__version__"]
