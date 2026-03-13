from datetime import datetime, timezone

def bytes_to_gb(value):
    if value is None:
        return 0
    return round(value / (1024 ** 3), 2)

def bytes_to_mb(value):
    if value is None:
        return 0
    return round(value / (1024 ** 2), 2)

def format_rate_bps(value):
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

def format_uptime(seconds):
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

def format_last_seen(iso_value):
    if not iso_value:
        return "Never"
    try:
        dt = datetime.fromisoformat(iso_value)
        now = datetime.now(timezone.utc)
        seconds = int((now - dt).total_seconds())
        if seconds < 60:
            return f"{seconds}s ago"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        return f"{seconds // 86400}d ago"
    except Exception:
        return iso_value
