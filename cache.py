# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/cache.py

import asyncio
import logging
from typing import Any, Optional
from diskcache import Cache
from config import settings

logger = logging.getLogger(__name__)

class AsyncDiskCache:
    def __init__(self, directory: str = settings.CACHE_DIR, default_ttl: int = settings.CACHE_DEFAULT_TTL):
        self._cache = Cache(directory)
        self._default_ttl = default_ttl
        logger.info(f"Initialized persistent TTL disk cache at: {directory}")

    async def get(self, key: str) -> Optional[Any]:
        """Retrieve a value asynchronously from the cache."""
        try:
            return await asyncio.to_thread(self._cache.get, key)
        except Exception as e:
            logger.error(f"Error reading key '{key}' from cache: {e}")
            return None

    async def set(self, key: str, value: Any, expire: Optional[int] = None) -> None:
        """Store a value asynchronously in the cache with a specific or default TTL."""
        ttl = expire if expire is not None else self._default_ttl
        try:
            await asyncio.to_thread(self._cache.set, key, value, expire=ttl)
        except Exception as e:
            logger.error(f"Error setting key '{key}' in cache: {e}")

    async def delete(self, key: str) -> bool:
        """Delete a key from the cache asynchronously."""
        try:
            return await asyncio.to_thread(self._cache.delete, key)
        except Exception as e:
            logger.error(f"Error deleting key '{key}' from cache: {e}")
            return False

    async def clear(self) -> None:
        """Clear all contents from the cache asynchronously."""
        try:
            await asyncio.to_thread(self._cache.clear)
            logger.info("Cache cleared successfully.")
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")

    async def clear_prefix(self, prefix: str) -> int:
        """Delete all keys matching a prefix. Returns count of deleted keys."""
        try:
            keys_to_delete = [k for k in self._cache.iterkeys() if k.startswith(prefix)]
            for key in keys_to_delete:
                await asyncio.to_thread(self._cache.delete, key)
            if keys_to_delete:
                logger.info(f"Cleared {len(keys_to_delete)} cache keys with prefix '{prefix}'.")
            return len(keys_to_delete)
        except Exception as e:
            logger.error(f"Error clearing prefix '{prefix}' from cache: {e}")
            return 0

# Global singleton cache instance
bot_cache = AsyncDiskCache()
