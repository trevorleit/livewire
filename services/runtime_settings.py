from database import get_db, DEFAULT_SETTINGS
from config import (
    OFFLINE_AFTER_SECONDS as DEFAULT_OFFLINE_AFTER_SECONDS,
    REFRESH_SECONDS as DEFAULT_REFRESH_SECONDS,
    MAX_TOP_PROCESSES as DEFAULT_MAX_TOP_PROCESSES,
    CPU_ALERT_THRESHOLD as DEFAULT_CPU_ALERT_THRESHOLD,
    RAM_ALERT_THRESHOLD as DEFAULT_RAM_ALERT_THRESHOLD,
    DISK_ALERT_THRESHOLD as DEFAULT_DISK_ALERT_THRESHOLD,
    TEMP_ALERT_THRESHOLD as DEFAULT_TEMP_ALERT_THRESHOLD,
)

def fetch_settings():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT setting_key, setting_value FROM settings")
    rows = cur.fetchall()
    conn.close()
    settings = dict(DEFAULT_SETTINGS)
    for row in rows:
        settings[row["setting_key"]] = row["setting_value"]
    return settings

def get_int_setting(settings, key, fallback):
    try:
        return int(float(settings.get(key, fallback)))
    except Exception:
        return fallback

def get_float_setting(settings, key, fallback):
    try:
        return float(settings.get(key, fallback))
    except Exception:
        return fallback

def get_runtime_settings():
    settings = fetch_settings()
    return {
        "cpu_alert_threshold": get_float_setting(settings, "cpu_alert_threshold", DEFAULT_CPU_ALERT_THRESHOLD),
        "ram_alert_threshold": get_float_setting(settings, "ram_alert_threshold", DEFAULT_RAM_ALERT_THRESHOLD),
        "disk_alert_threshold": get_float_setting(settings, "disk_alert_threshold", DEFAULT_DISK_ALERT_THRESHOLD),
        "temp_alert_threshold": get_float_setting(settings, "temp_alert_threshold", DEFAULT_TEMP_ALERT_THRESHOLD),
        "refresh_seconds": get_int_setting(settings, "refresh_seconds", DEFAULT_REFRESH_SECONDS),
        "offline_after_seconds": get_int_setting(settings, "offline_after_seconds", DEFAULT_OFFLINE_AFTER_SECONDS),
        "max_top_processes": get_int_setting(settings, "max_top_processes", DEFAULT_MAX_TOP_PROCESSES),
    }
