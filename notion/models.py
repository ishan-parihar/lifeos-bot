# Path: /home/ishanp/Documents/GitHub/MY-PROJECTS/LIFEOS/lifeos-bot/notion/models.py

from typing import Dict, Any, List, Optional

class NotionPayloadBuilder:
    @staticmethod
    def title(text: str) -> Dict[str, Any]:
        """Build title property JSON payload."""
        return {"title": [{"text": {"content": text}}]}

    @staticmethod
    def rich_text(text: str) -> Dict[str, Any]:
        """Build rich text property JSON payload."""
        return {"rich_text": [{"text": {"content": text}}]}

    @staticmethod
    def select(option_name: Optional[str]) -> Dict[str, Any]:
        """Build select property JSON payload."""
        if not option_name:
            return {"select": None}
        return {"select": {"name": option_name}}

    @staticmethod
    def multi_select(option_names: List[str]) -> Dict[str, Any]:
        """Build multi-select property JSON payload."""
        return {"multi_select": [{"name": name} for name in option_names]}

    @staticmethod
    def number(value: Optional[float]) -> Dict[str, Any]:
        """Build number property JSON payload."""
        return {"number": value}

    @staticmethod
    def date(iso_str: Optional[str], end_iso: Optional[str] = None) -> Dict[str, Any]:
        """Build date property JSON payload (requires ISO 8601 string). Supports date ranges."""
        if not iso_str:
            return {"date": None}
        date_obj: Dict[str, Any] = {"start": iso_str}
        if end_iso:
            date_obj["end"] = end_iso
        return {"date": date_obj}

    @staticmethod
    def checkbox(checked: bool) -> Dict[str, Any]:
        """Build checkbox property JSON payload."""
        return {"checkbox": checked}
