# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/notion/discovery.py

import logging
import os
import re
from typing import Dict
from notion_client import AsyncClient

logger = logging.getLogger(__name__)

# Canonical database names to search for (lowercase for matching)
DB_NAME_MAP = {
    "activity-log": "DATABASE_ID_ACTIVITY_LOG",
    "financial-log": "DATABASE_ID_FINANCIAL_LOG",
    "diet-log": "DATABASE_ID_DIET_LOG",
    "subjective-journal": "DATABASE_ID_SUBJECTIVE_JOURNAL",
    "relational-journal": "DATABASE_ID_RELATIONAL_JOURNAL",
    "systemic-journal": "DATABASE_ID_SYSTEMIC_JOURNAL",
}

ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")


def _normalize(name: str) -> str:
    """Lowercase, strip, collapse whitespace/hyphens for fuzzy matching."""
    return re.sub(r"[\s_]+", "-", name.strip().lower())


async def discover_databases(notion_token: str) -> Dict[str, str]:
    """
    Searches the Notion workspace for all databases matching the canonical names.
    Returns a dict mapping ENV_VAR_NAME -> database_id.
    """
    client = AsyncClient(auth=notion_token)
    found: Dict[str, str] = {}

    logger.info("Searching Notion workspace for LifeOS databases...")

    # Search for all databases accessible to the integration.
    # Notion API now uses "data_source" instead of "database" for the object filter.
    try:
        response = await client.search(
            query="",
            filter={"value": "data_source", "property": "object"},
            page_size=100,
        )
    except Exception as e:
        logger.error(f"Notion search failed: {e}")
        await client.aclose()
        return found

    databases = response.get("results", [])

    # Also fetch additional pages if there are more
    while response.get("has_more") and response.get("next_cursor"):
        try:
            response = await client.search(
                query="",
                filter={"value": "data_source", "property": "object"},
                page_size=100,
                start_cursor=response["next_cursor"],
            )
            databases.extend(response.get("results", []))
        except Exception as e:
            logger.error(f"Notion pagination search failed: {e}")
            break

    logger.info(f"Found {len(databases)} databases in workspace. Matching against target names...")

    for db in databases:
        title_parts = db.get("title", [])
        if not title_parts:
            continue

        db_title = "".join(part.get("plain_text", "") for part in title_parts)
        # Use parent.database_id — the data_source ID doesn't work with Notion API operations
        parent = db.get("parent", {})
        db_id = parent.get("database_id", "") if parent.get("type") == "database_id" else db.get("id", "")
        normalized = _normalize(db_title)

        for target_name, env_var in DB_NAME_MAP.items():
            if _normalize(target_name) == normalized:
                found[env_var] = db_id
                logger.info(f"  Matched '{db_title}' -> {env_var} = {db_id}")
                break

    await client.aclose()

    missing = set(DB_NAME_MAP.values()) - set(found.keys())
    if missing:
        logger.warning(f"Could not find databases for: {missing}")

    return found


def _read_env() -> str:
    """Reads current .env contents."""
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            return f.read()
    return ""


def write_ids_to_env(ids: Dict[str, str]) -> None:
    """
    Writes discovered database IDs into the .env file.
    Updates existing lines in place; appends missing ones.
    """
    content = _read_env()
    lines = content.splitlines()
    updated = False

    for env_var, db_id in ids.items():
        pattern = re.compile(rf"^{re.escape(env_var)}=.*$", re.MULTILINE)
        new_line = f"{env_var}={db_id}"

        if pattern.search(content):
            content = pattern.sub(new_line, content)
            updated = True
        else:
            lines.append(new_line)
            updated = True

    if updated:
        # Rebuild from content (which has in-place substitutions) + any appended lines
        with open(ENV_PATH, "w") as f:
            f.write(content if content.endswith("\n") else content + "\n")
        logger.info(f"Updated .env with {len(ids)} database ID(s).")


async def ensure_database_ids(notion_token: str) -> Dict[str, str]:
    """
    Main entry point: discovers databases and persists IDs to .env.
    Returns the mapping of ENV_VAR -> database_id.
    """
    ids = await discover_databases(notion_token)

    if ids:
        write_ids_to_env(ids)
        logger.info(f"Database discovery complete. Found {len(ids)}/{len(DB_NAME_MAP)} databases.")
    else:
        logger.error("No databases discovered. Check Notion integration permissions.")

    return ids
