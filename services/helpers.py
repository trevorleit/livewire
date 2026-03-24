from datetime import datetime, timezone
from typing import Any, Optional

from database import get_db


def bytes_to_gb(value: Any) -> float:
    if value is None:
        return 0
    try:
        return round(float(value) / (1024 ** 3), 2)
    except Exception:
        return 0


def bytes_to_mb(value: Any) -> float:
    if value is None:
        return 0
    try:
        return round(float(value) / (1024 ** 2), 2)
    except Exception:
        return 0


def mb_to_gb(value: Any) -> float:
    if value is None:
        return 0
    try:
        return round(float(value) / 1024, 2)
    except Exception:
        return 0


def format_rate_bps(value: Any) -> str:
    if value is None:
        return "0 B/s"
    try:
        value = float(value)
    except Exception:
        return "0 B/s"

    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024.0
        idx += 1
    return f"{value:.2f} {units[idx]}"


def format_uptime(seconds: Any) -> str:
    try:
        seconds = int(seconds or 0)
    except Exception:
        return "0m"

    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None

    text = str(value).strip()
    if not text:
        return None

    try:
        text = text.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def format_last_seen(iso_value: Any) -> str:
    dt = _parse_datetime(iso_value)
    if not dt:
        return "Never"

    try:
        now = datetime.now(timezone.utc)
        seconds = int((now - dt).total_seconds())

        if seconds < 0:
            return "Just now"
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except Exception:
        return str(iso_value)


def seconds_since(iso_value: Any) -> Optional[int]:
    dt = _parse_datetime(iso_value)
    if not dt:
        return None

    try:
        now = datetime.now(timezone.utc)
        return max(int((now - dt).total_seconds()), 0)
    except Exception:
        return None


def is_stale(iso_value: Any, stale_after_seconds: int = 120) -> bool:
    age = seconds_since(iso_value)
    if age is None:
        return True
    return age > stale_after_seconds


def freshness_state(
    iso_value: Any,
    fresh_after_seconds: int = 90,
    aging_after_seconds: int = 180,
) -> str:
    """
    Returns one of:
    - "unknown"
    - "fresh"
    - "aging"
    - "stale"
    """
    age = seconds_since(iso_value)
    if age is None:
        return "unknown"
    if age <= fresh_after_seconds:
        return "fresh"
    if age <= aging_after_seconds:
        return "aging"
    return "stale"


def freshness_label(
    iso_value: Any,
    fresh_after_seconds: int = 90,
    aging_after_seconds: int = 180,
) -> str:
    state = freshness_state(
        iso_value,
        fresh_after_seconds=fresh_after_seconds,
        aging_after_seconds=aging_after_seconds,
    )

    labels = {
        "unknown": "Unknown",
        "fresh": "Fresh",
        "aging": "Aging",
        "stale": "Stale",
    }
    return labels.get(state, "Unknown")


def freshness_badge_class(
    iso_value: Any,
    fresh_after_seconds: int = 90,
    aging_after_seconds: int = 180,
) -> str:
    state = freshness_state(
        iso_value,
        fresh_after_seconds=fresh_after_seconds,
        aging_after_seconds=aging_after_seconds,
    )

    mapping = {
        "unknown": "pill-muted",
        "fresh": "pill-online",
        "aging": "pill-warning",
        "stale": "pill-offline",
    }
    return mapping.get(state, "pill-muted")


def get_runtime_settings() -> dict:
    defaults = {
        "dashboard_refresh_seconds": 30,
        "freshness_fresh_seconds": 90,
        "freshness_aging_seconds": 300,
    }

    try:
        db = get_db()
        cur = db.cursor()
        cur.execute(
            """
            SELECT key, value
            FROM runtime_settings
            WHERE key IN (?, ?, ?)
            """,
            (
                "dashboard_refresh_seconds",
                "freshness_fresh_seconds",
                "freshness_aging_seconds",
            ),
        )
        rows = cur.fetchall()

        settings = dict(defaults)

        for row in rows:
            key = row["key"]
            raw_value = row["value"]

            try:
                settings[key] = int(raw_value)
            except Exception:
                settings[key] = defaults.get(key, raw_value)

        return settings
    except Exception:
        return defaults