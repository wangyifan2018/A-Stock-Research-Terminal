"""
统一的缓存管理模块。

提供全局缓存机制，避免重复的网络请求，提升性能。
"""

from __future__ import annotations

import hashlib
import os
import pickle
import sqlite3
import time
from pathlib import Path
from threading import RLock
from typing import Any, Callable, Protocol, TypeVar
from functools import wraps

T = TypeVar('T')


class CacheBackend(Protocol):
    """缓存后端协议。"""

    def get(self, key: str) -> Any | None:
        ...

    def get_with_stale(self, key: str, max_stale_ttl: float) -> tuple[Any | None, bool]:
        ...

    def set(self, key: str, value: Any, ttl: float) -> None:
        ...

    def clear(self) -> None:
        ...


class CacheEntry:
    """缓存条目"""
    def __init__(self, value: Any, ttl: float):
        self.value = value
        self.timestamp = time.time()
        self.ttl = ttl

    def is_expired(self) -> bool:
        """检查是否过期"""
        return time.time() - self.timestamp > self.ttl


class SimpleCache:
    """简单的内存缓存"""

    def __init__(self):
        self._cache: dict[str, CacheEntry] = {}

    def get(self, key: str) -> Any | None:
        """获取缓存值"""
        entry = self._cache.get(key)
        if entry is None:
            return None

        if entry.is_expired():
            del self._cache[key]
            return None

        return entry.value

    def get_with_stale(self, key: str, max_stale_ttl: float) -> tuple[Any | None, bool]:
        """获取缓存值；允许返回过期但仍在 stale 窗口内的数据。"""
        entry = self._cache.get(key)
        if entry is None:
            return None, False

        age = time.time() - entry.timestamp
        if age <= entry.ttl:
            return entry.value, False
        if age <= entry.ttl + max_stale_ttl:
            return entry.value, True
        del self._cache[key]
        return None, False

    def set(self, key: str, value: Any, ttl: float) -> None:
        """设置缓存值"""
        self._cache[key] = CacheEntry(value, ttl)

    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()

    def remove_expired(self) -> int:
        """移除过期条目，返回移除数量"""
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired()
        ]
        for key in expired_keys:
            del self._cache[key]
        return len(expired_keys)


class SQLiteCache:
    """SQLite 持久化缓存，适合财报等低频变更数据。"""

    def __init__(self, path: str | os.PathLike[str] | None = None):
        cache_path = Path(
            path
            or os.getenv("OPENFR_SQLITE_CACHE_PATH")
            or ".openfr_cache/cache.sqlite3"
        )
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.path = cache_path
        self._lock = RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5.0, check_same_thread=False)

    def _init_db(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache_entries (
                    key TEXT PRIMARY KEY,
                    value BLOB NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_cache_entries_expires_at ON cache_entries(expires_at)"
            )

    def get(self, key: str) -> Any | None:
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            value_blob, expires_at = row
            if expires_at <= now:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                return None
            try:
                return pickle.loads(value_blob)
            except Exception:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                return None

    def get_with_stale(self, key: str, max_stale_ttl: float) -> tuple[Any | None, bool]:
        now = time.time()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value, expires_at FROM cache_entries WHERE key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None, False
            value_blob, expires_at = row
            if expires_at + max_stale_ttl <= now:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                return None, False
            try:
                value = pickle.loads(value_blob)
            except Exception:
                conn.execute("DELETE FROM cache_entries WHERE key = ?", (key,))
                return None, False
            return value, expires_at <= now

    def set(self, key: str, value: Any, ttl: float) -> None:
        now = time.time()
        expires_at = now + ttl
        value_blob = pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO cache_entries (key, value, expires_at, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (key, value_blob, expires_at, now),
            )

    def clear(self) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM cache_entries")

    def remove_expired(self) -> int:
        now = time.time()
        with self._lock, self._connect() as conn:
            cursor = conn.execute("DELETE FROM cache_entries WHERE expires_at <= ?", (now,))
            return cursor.rowcount


class TieredCache:
    """内存 + SQLite 双层缓存。"""

    def __init__(self, memory: SimpleCache, persistent: SQLiteCache | None = None):
        self.memory = memory
        self.persistent = persistent

    def get(self, key: str) -> Any | None:
        value = self.memory.get(key)
        if value is not None:
            return value
        if self.persistent is None:
            return None
        value = self.persistent.get(key)
        if value is not None:
            # SQLite 命中后回填内存，短期重复请求无需再反序列化。
            self.memory.set(key, value, ttl=60.0)
        return value

    def get_with_stale(self, key: str, max_stale_ttl: float) -> tuple[Any | None, bool]:
        value, is_stale = self.memory.get_with_stale(key, max_stale_ttl)
        if value is not None:
            return value, is_stale
        if self.persistent is None:
            return None, False
        value, is_stale = self.persistent.get_with_stale(key, max_stale_ttl)
        if value is not None and not is_stale:
            self.memory.set(key, value, ttl=60.0)
        return value, is_stale

    def set(self, key: str, value: Any, ttl: float) -> None:
        self.memory.set(key, value, ttl)
        if self.persistent is not None:
            self.persistent.set(key, value, ttl)

    def clear(self) -> None:
        self.memory.clear()
        if self.persistent is not None:
            self.persistent.clear()

    def remove_expired(self) -> int:
        removed = self.memory.remove_expired()
        if self.persistent is not None:
            removed += self.persistent.remove_expired()
        return removed


def _make_global_cache() -> CacheBackend:
    backend = os.getenv("OPENFR_CACHE_BACKEND", "sqlite").lower()
    memory = SimpleCache()
    if backend in ("none", "memory", "inmemory"):
        return memory
    return TieredCache(memory, SQLiteCache())


# 全局缓存实例
_global_cache: CacheBackend = _make_global_cache()


def make_cache_key(func: Callable[..., Any], args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """为函数调用生成稳定且长度可控的缓存键。"""
    payload = pickle.dumps((func.__module__, func.__qualname__, args, sorted(kwargs.items())), protocol=4)
    digest = hashlib.sha256(payload).hexdigest()
    return f"{func.__module__}.{func.__qualname__}:{digest}"


def cached(ttl: float = 300.0, key_func: Callable[..., str] | None = None):
    """
    缓存装饰器。

    Args:
        ttl: 缓存有效期（秒）
        key_func: 自定义缓存键生成函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            # 生成缓存键
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = make_cache_key(func, args, kwargs)

            # 尝试从缓存获取
            cached_value = _global_cache.get(cache_key)
            if cached_value is not None:
                return cached_value

            # 执行函数并缓存结果
            result = func(*args, **kwargs)
            _global_cache.set(cache_key, result, ttl)
            return result

        return wrapper
    return decorator


def _mark_stale(value: T) -> T:
    """Return a stale-marked copy when the value type supports attrs (e.g. DataFrame)."""
    if hasattr(value, "attrs") and hasattr(value, "copy"):
        try:
            copied = value.copy()
            copied.attrs["_openfr_stale"] = True
            return copied
        except Exception:
            pass
    return value


def stale_cached(
    ttl: float = 300.0,
    stale_ttl: float = 24 * 60 * 60,
    key_func: Callable[..., str] | None = None,
):
    """
    缓存装饰器：实时请求失败时允许返回过期缓存。

    适用于上游偶发断连但旧数据仍比空结果更有价值的接口。
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            if key_func:
                cache_key = key_func(*args, **kwargs)
            else:
                cache_key = make_cache_key(func, args, kwargs)

            cached_value, is_stale = _global_cache.get_with_stale(cache_key, stale_ttl)
            if cached_value is not None and not is_stale:
                return cached_value

            try:
                result = func(*args, **kwargs)
            except Exception:
                if cached_value is not None:
                    return _mark_stale(cached_value)
                raise

            _global_cache.set(cache_key, result, ttl)
            return result

        return wrapper
    return decorator


def persistent_cached(ttl: float = 24 * 60 * 60, key_func: Callable[..., str] | None = None):
    """语义化别名：用于财报、列表等低频变更数据的 SQLite 本地缓存。"""
    return cached(ttl=ttl, key_func=key_func)


def get_cache() -> CacheBackend:
    """获取全局缓存实例"""
    return _global_cache


def clear_cache() -> None:
    """清空全局缓存"""
    _global_cache.clear()
