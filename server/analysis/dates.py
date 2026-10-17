"""Calendar date validation shared by analysis and provider adapters."""
from datetime import date
import re


def validate_date(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Dates must use YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def event_date_fields(event: dict, entry_date: str) -> dict:
    source = event.get("date_source")
    if source not in {"explicit", "relative", "entry_date"}:
        raise ValueError("Invalid event date_source")
    value = validate_date(event.get("event_date"))
    if source == "entry_date" and value != entry_date:
        raise ValueError("Fallback event date must equal entry_date")
    return {"event_date": value, "date_source": source}
