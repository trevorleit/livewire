from flask import Blueprint, render_template, request, redirect, url_for
from database import get_db
from services.runtime_settings import fetch_settings
from config import (
    OFFLINE_AFTER_SECONDS as DEFAULT_OFFLINE_AFTER_SECONDS,
    REFRESH_SECONDS as DEFAULT_REFRESH_SECONDS,
    MAX_TOP_PROCESSES as DEFAULT_MAX_TOP_PROCESSES,
    CPU_ALERT_THRESHOLD as DEFAULT_CPU_ALERT_THRESHOLD,
    RAM_ALERT_THRESHOLD as DEFAULT_RAM_ALERT_THRESHOLD,
    DISK_ALERT_THRESHOLD as DEFAULT_DISK_ALERT_THRESHOLD,
    TEMP_ALERT_THRESHOLD as DEFAULT_TEMP_ALERT_THRESHOLD,
)

settings_bp = Blueprint("settings", __name__)

@settings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        updates = {
            "cpu_alert_threshold": request.form.get("cpu_alert_threshold", DEFAULT_CPU_ALERT_THRESHOLD),
            "ram_alert_threshold": request.form.get("ram_alert_threshold", DEFAULT_RAM_ALERT_THRESHOLD),
            "disk_alert_threshold": request.form.get("disk_alert_threshold", DEFAULT_DISK_ALERT_THRESHOLD),
            "temp_alert_threshold": request.form.get("temp_alert_threshold", DEFAULT_TEMP_ALERT_THRESHOLD),
            "refresh_seconds": request.form.get("refresh_seconds", DEFAULT_REFRESH_SECONDS),
            "offline_after_seconds": request.form.get("offline_after_seconds", DEFAULT_OFFLINE_AFTER_SECONDS),
            "max_top_processes": request.form.get("max_top_processes", DEFAULT_MAX_TOP_PROCESSES),
        }
        conn = get_db()
        cur = conn.cursor()
        for key, value in updates.items():
            cur.execute("""
                INSERT INTO settings (setting_key, setting_value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(setting_key)
                DO UPDATE SET setting_value = excluded.setting_value, updated_at = CURRENT_TIMESTAMP
            """, (key, str(value)))
        conn.commit()
        conn.close()
        return redirect(url_for("settings.settings"))

    settings_map = fetch_settings()
    return render_template("settings.html", settings_map=settings_map)
