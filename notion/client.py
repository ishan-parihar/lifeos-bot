# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/notion/client.py

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from notion_client import AsyncClient
from config import settings
from cache import bot_cache

logger = logging.getLogger(__name__)

# Activity Types relation database ID
ACTIVITY_TYPES_DB_ID = "211c18ce-5aab-8065-a9f3-db3e828e89e7"


class NotionClientManager:
    def __init__(self):
        # Use 2022-06-28 API version — newer versions don't return properties in databases.retrieve()
        self.client = AsyncClient(auth=settings.NOTION_API_KEY, notion_version="2022-06-28")
        self._schema_logged = False

    async def get_select_property_options(self, database_id: str, property_name: str) -> List[str]:
        """
        Retrieves the options for a Select or Multi-Select field from a Notion database schema.
        Caches options dynamically for 24 hours to ensure instantaneous menu rendering.
        """
        if not database_id or "placeholder" in database_id:
            logger.warning(f"Using placeholder database ID for property '{property_name}'. Skipping Notion fetch.")
            return []

        cache_key = f"notion_schema_opts:{database_id}:{property_name}"
        cached_opts = await bot_cache.get(cache_key)
        if cached_opts is not None:
            return cached_opts

        logger.info(f"Fetching schema options for '{property_name}' from Notion API...")
        try:
            db_info = await self.client.databases.retrieve(database_id=database_id)
            prop = db_info.get("properties", {}).get(property_name, {})

            options = []
            if prop.get("type") == "select":
                options = [opt["name"] for opt in prop.get("select", {}).get("options", [])]
            elif prop.get("type") == "multi_select":
                options = [opt["name"] for opt in prop.get("multi_select", {}).get("options", [])]

            await bot_cache.set(cache_key, options, expire=settings.CACHE_STATIC_TTL)
            return options
        except Exception as e:
            logger.error(f"Failed to fetch Notion schema for property '{property_name}': {e}")
            return []

    async def get_activity_types(self) -> List[Dict[str, str]]:
        """
        Fetches activity types from the Activity Types relation database.
        Returns list of {name, category, habit, frequency, duration_hrs}.
        Cached for 24 hours.
        """
        cache_key = "activity_types_list"
        cached = await bot_cache.get(cache_key)
        if cached is not None:
            return cached

        logger.info("Fetching activity types from relation DB...")
        try:
            response = await self.client.request(
                path=f"databases/{ACTIVITY_TYPES_DB_ID}/query",
                method="POST",
                body={"page_size": 100},
            )
            types = []
            for page in response.get("results", []):
                props = page.get("properties", {})
                title_parts = props.get("Activity Types", {}).get("title", [])
                name = "".join(p.get("plain_text", "") for p in title_parts)
                if not name:
                    continue
                cat = props.get("category", {}).get("select")
                habit = props.get("Habit", {}).get("checkbox", False)
                freq = props.get("Frequency", {}).get("select")
                dur = props.get("Duration (in hrs)", {}).get("number")
                types.append({
                    "name": name,
                    "category": cat.get("name", "") if cat else "",
                    "habit": habit,
                    "frequency": freq.get("name", "") if freq else "",
                    "duration_hrs": dur,
                })

            await bot_cache.set(cache_key, types, expire=settings.CACHE_STATIC_TTL)
            return types
        except Exception as e:
            logger.error(f"Failed to fetch activity types: {e}")
            return []

    @staticmethod
    def _ist_date_to_utc_start(date_str: str) -> str:
        """
        Converts a local date to the UTC start boundary.
        IST midnight = previous day 18:30 UTC, so subtract 1 day.
        """
        from datetime import date as _date
        d = _date.fromisoformat(date_str)
        return (d - timedelta(days=1)).isoformat()

    @staticmethod
    def _ist_date_to_utc_end(date_str: str) -> str:
        """
        Converts a local date end to the UTC end boundary.
        IST end-of-day = next day 18:30 UTC, so add 1 day.
        """
        from datetime import date as _date
        d = _date.fromisoformat(date_str)
        return (d + timedelta(days=1)).isoformat()

    async def query_activity_entries(
        self, start_date: str, end_date: str, page_size: int = 100,
        sort_ascending: bool = True, local_dates: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Queries activity log entries within a date range.
        Dates should be ISO format (YYYY-MM-DD or ISO datetime).
        If local_dates=True (default), converts date strings to UTC range
        to account for IST timezone offset.
        Returns sorted list of parsed entries.
        Cached per date range for 5 minutes.
        """
        cache_key = f"activity_entries:{start_date}:{end_date}:{sort_ascending}:{local_dates}"
        cached = await bot_cache.get(cache_key)
        if cached is not None:
            return cached

        # Convert local dates to UTC boundaries if needed
        filter_start = start_date
        filter_end = end_date
        if local_dates and len(start_date) == 10:  # YYYY-MM-DD format
            filter_start = self._ist_date_to_utc_start(start_date)
            filter_end = self._ist_date_to_utc_end(end_date)

        sort_dir = "ascending" if sort_ascending else "descending"
        logger.info(f"Querying activity entries from {start_date} to {end_date} (filter: {filter_start} to {filter_end}, {sort_dir})...")
        try:
            response = await self.client.request(
                path=f"databases/{settings.DATABASE_ID_ACTIVITY_LOG}/query",
                method="POST",
                body={
                    "filter": {
                        "and": [
                            {"property": "Date", "date": {"on_or_after": filter_start}},
                            {"property": "Date", "date": {"before": filter_end}},
                        ]
                    },
                    "sorts": [{"property": "Date", "direction": sort_dir}],
                    "page_size": page_size,
                },
            )

            await self._log_db_schema_if_needed(settings.DATABASE_ID_ACTIVITY_LOG)

            entries = []
            for page in response.get("results", []):
                entry = self._parse_activity_entry(page)
                if entry:
                    entries.append(entry)

            # Always return in ascending order regardless of sort direction
            if not sort_ascending:
                entries.reverse()

            await bot_cache.set(cache_key, entries, expire=settings.CACHE_DEFAULT_TTL)
            return entries
        except Exception as e:
            logger.error(f"Failed to query activity entries: {e}")
            return []

    async def _log_db_schema_if_needed(self, database_id: str) -> None:
        """Logs the database property names/types once per session to aid debugging."""
        if self._schema_logged or not database_id or "placeholder" in database_id:
            return
        try:
            db_info = await self.client.databases.retrieve(database_id=database_id)
            props = db_info.get("properties", {})
            schema = {name: p.get("type", "?") for name, p in props.items()}
            logger.info(f"Activity Log DB schema: {schema}")
            self._schema_logged = True
        except Exception as e:
            logger.warning(f"Could not log DB schema: {e}")

    def _parse_activity_entry(self, page: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Parses a raw Notion page into a clean activity entry dict."""
        try:
            props = page.get("properties", {})

            # Title
            title_parts = props.get("Name", {}).get("title", [])
            title = "".join(p.get("plain_text", "") for p in title_parts)

            # Date
            date_prop = props.get("Date", {}).get("date", {})
            if not date_prop:
                return None
            start_str = date_prop.get("start", "")
            end_str = date_prop.get("end", "")

            # Parse datetimes
            start_dt = datetime.fromisoformat(start_str) if start_str else None
            end_dt = datetime.fromisoformat(end_str) if end_str else None

            # Computed formula results
            act_type = props.get("Activity Type", {})
            activity_type = act_type.get("formula", {}).get("string", "") if act_type.get("type") == "formula" else ""

            duration_prop = props.get("Duration", {})
            duration = duration_prop.get("formula", {}).get("number", 0) if duration_prop.get("type") == "formula" else 0

            entry_id = props.get("ID", {}).get("unique_id", {})
            prefix = entry_id.get("prefix", "")
            num = entry_id.get("number", "")
            id_str = f"{prefix}{num}" if prefix else str(num)

            return {
                "id": id_str,
                "page_id": page.get("id", ""),
                "title": title,
                "activity_type": activity_type,
                "start": start_dt,
                "end": end_dt,
                "duration_hrs": duration,
            }
        except Exception as e:
            logger.error(f"Failed to parse activity entry: {e}")
            return None

    async def create_page(self, database_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Creates a page in a specific Notion database asynchronously."""
        try:
            logger.info(f"Creating new page in database '{database_id}'...")
            result = await self.client.pages.create(
                parent={"database_id": database_id},
                properties=properties,
            )
            # Invalidate activity entry caches on new entry
            if database_id == settings.DATABASE_ID_ACTIVITY_LOG:
                await self._invalidate_activity_cache()
            return result
        except Exception as e:
            logger.error(f"Failed to create Notion page: {e}")
            raise e

    async def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        """Updates properties on an existing Notion page."""
        try:
            logger.info(f"Updating page {page_id}...")
            result = await self.client.pages.update(page_id=page_id, properties=properties)
            await self._invalidate_activity_cache()
            return result
        except Exception as e:
            logger.error(f"Failed to update page: {e}")
            raise e

    async def delete_page(self, page_id: str) -> Dict[str, Any]:
        """Archives (soft-deletes) a Notion page."""
        try:
            logger.info(f"Archiving page {page_id}...")
            result = await self.client.pages.update(page_id=page_id, archived=True)
            await self._invalidate_activity_cache()
            return result
        except Exception as e:
            logger.error(f"Failed to delete page: {e}")
            raise e

    async def _invalidate_activity_cache(self) -> None:
        """Clears ALL cached activity entries after any mutation.
        Uses prefix-based deletion to cover every possible date range,
        not just hardcoded ones.
        """
        await bot_cache.clear_prefix("activity_entries:")


# Global singleton client
notion_manager = NotionClientManager()
