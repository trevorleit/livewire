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


def _get_settings_columns(cur):
    cols = {
        row["name"] for row in cur.execute("PRAGMA table_info(settings)").fetchall()
    }

    if "setting_key" in cols and "setting_value" in cols:
        return "setting_key", "setting_value"

    if "key" in cols and "value" in cols:
        return "key", "value"

    return None, None


def fetch_settings():
    conn = get_db()
    try:
        cur = conn.cursor()

        key_col, value_col = _get_settings_columns(cur)
        settings = dict(DEFAULT_SETTINGS)

        if not key_col or not value_col:
            return settings

        cur.execute(f"SELECT {key_col}, {value_col} FROM settings")
        rows = cur.fetchall()

        for row in rows:
            settings[row[key_col]] = row[value_col]

        return settings
    finally:
        conn.close()


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


def get_bool_setting(settings, key, fallback=False):
    raw = str(settings.get(key, "1" if fallback else "0")).strip().lower()
    return raw in {"1", "true", "yes", "on", "enabled"}


def get_runtime_settings():
    settings = fetch_settings()

    return {
        # ---------------------------------
        # Existing settings
        # ---------------------------------
        "cpu_alert_threshold": get_float_setting(settings, "cpu_alert_threshold", DEFAULT_CPU_ALERT_THRESHOLD),
        "ram_alert_threshold": get_float_setting(settings, "ram_alert_threshold", DEFAULT_RAM_ALERT_THRESHOLD),
        "disk_alert_threshold": get_float_setting(settings, "disk_alert_threshold", DEFAULT_DISK_ALERT_THRESHOLD),
        "temp_alert_threshold": get_float_setting(settings, "temp_alert_threshold", DEFAULT_TEMP_ALERT_THRESHOLD),
        "refresh_seconds": get_int_setting(settings, "refresh_seconds", DEFAULT_REFRESH_SECONDS),
        "offline_after_seconds": get_int_setting(settings, "offline_after_seconds", DEFAULT_OFFLINE_AFTER_SECONDS),
        "max_top_processes": get_int_setting(settings, "max_top_processes", DEFAULT_MAX_TOP_PROCESSES),

        # ---------------------------------
        # Notifications
        # ---------------------------------
        "discord_webhook_url": str(settings.get("discord_webhook_url", "")).strip(),
        "notification_email_to": str(settings.get("notification_email_to", "")).strip(),
        "smtp_host": str(settings.get("smtp_host", "")).strip(),
        "smtp_port": get_int_setting(settings, "smtp_port", 587),
        "smtp_username": str(settings.get("smtp_username", "")).strip(),
        "smtp_password": str(settings.get("smtp_password", "")),
        "smtp_use_tls": get_bool_setting(settings, "smtp_use_tls", True),
        "smtp_from": str(settings.get("smtp_from", "livewire@localhost")).strip() or "livewire@localhost",

        # ---------------------------------
        # 🔥 NEW: Hardware Monitoring (LHM)
        # ---------------------------------
        "enhanced_hwmon_enabled": get_bool_setting(settings, "enhanced_hwmon_enabled", False),
        "lhm_auto_install": get_bool_setting(settings, "lhm_auto_install", False),
        "lhm_auto_start": get_bool_setting(settings, "lhm_auto_start", False),

        "lhm_url": str(settings.get("lhm_url", "http://127.0.0.1:8085/data.json")).strip(),
        "lhm_install_dir": str(settings.get(
            "lhm_install_dir",
            r"C:\ProgramData\LiveWire\LibreHardwareMonitor"
        )).strip(),

        # optional (future-proof)
        "lhm_download_url": str(settings.get("lhm_download_url", "")).strip(),
        "lhm_expected_sha256": str(settings.get("lhm_expected_sha256", "")).strip(),
    }