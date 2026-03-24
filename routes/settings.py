from flask import Blueprint, render_template, request, redirect, url_for, flash

from database import get_db
from services.notification_service import send_test_notification
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


DEFAULT_LHM_URL = "http://127.0.0.1:8085/data.json"
DEFAULT_LHM_INSTALL_DIR = r"C:\ProgramData\LiveWire\LibreHardwareMonitor"
DEFAULT_LHM_DOWNLOAD_URL = (
    "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/"
    "releases/latest/download/LibreHardwareMonitor.zip"
)


def _get_settings_columns(cur):
    cols = {
        row["name"] for row in cur.execute("PRAGMA table_info(settings)").fetchall()
    }

    if "setting_key" in cols and "setting_value" in cols:
        return "setting_key", "setting_value", "updated_at" if "updated_at" in cols else None

    if "key" in cols and "value" in cols:
        return "key", "value", None

    return None, None, None


def _clean_text(value, fallback=""):
    return str(value or fallback).strip().strip('"').strip("'")


def _checkbox_value(form, key: str) -> str:
    return "1" if form.get(key) else "0"


def _save_setting(cur, key_col, value_col, updated_at_col, key, value):
    if updated_at_col:
        cur.execute(
            f"""
            INSERT INTO settings ({key_col}, {value_col}, {updated_at_col})
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT({key_col})
            DO UPDATE SET
                {value_col} = excluded.{value_col},
                {updated_at_col} = CURRENT_TIMESTAMP
            """,
            (key, str(value)),
        )
    else:
        cur.execute(
            f"""
            INSERT INTO settings ({key_col}, {value_col})
            VALUES (?, ?)
            ON CONFLICT({key_col})
            DO UPDATE SET {value_col} = excluded.{value_col}
            """,
            (key, str(value)),
        )


def _to_int(value, default, minimum=None, maximum=None):
    try:
        result = int(float(value))
    except Exception:
        result = int(default)

    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)

    return str(result)


def _to_float(value, default, minimum=None, maximum=None):
    try:
        result = float(value)
    except Exception:
        result = float(default)

    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)

    if result.is_integer():
        return str(int(result))
    return str(result)


@settings_bp.route("/settings", methods=["GET", "POST"])
def settings():
    if request.method == "POST":
        form_action = request.form.get("form_action", "save")

        lhm_enabled = _checkbox_value(request.form, "enhanced_hwmon_enabled")
        lhm_auto_install = _checkbox_value(request.form, "lhm_auto_install")
        lhm_auto_start = _checkbox_value(request.form, "lhm_auto_start")
        privacy_mode_enabled = _checkbox_value(request.form, "privacy_mode_enabled")

        lhm_url = _clean_text(
            request.form.get("lhm_url"),
            DEFAULT_LHM_URL,
        ) or DEFAULT_LHM_URL

        lhm_install_dir = _clean_text(
            request.form.get("lhm_install_dir"),
            DEFAULT_LHM_INSTALL_DIR,
        ) or DEFAULT_LHM_INSTALL_DIR

        lhm_download_url = _clean_text(
            request.form.get("lhm_download_url"),
            DEFAULT_LHM_DOWNLOAD_URL,
        ) or DEFAULT_LHM_DOWNLOAD_URL

        lhm_expected_sha256 = _clean_text(
            request.form.get("lhm_expected_sha256"),
            "",
        )

        updates = {
            "cpu_alert_threshold": _to_float(
                request.form.get("cpu_alert_threshold"),
                DEFAULT_CPU_ALERT_THRESHOLD,
                minimum=1,
                maximum=100,
            ),
            "ram_alert_threshold": _to_float(
                request.form.get("ram_alert_threshold"),
                DEFAULT_RAM_ALERT_THRESHOLD,
                minimum=1,
                maximum=100,
            ),
            "disk_alert_threshold": _to_float(
                request.form.get("disk_alert_threshold"),
                DEFAULT_DISK_ALERT_THRESHOLD,
                minimum=1,
                maximum=100,
            ),
            "temp_alert_threshold": _to_float(
                request.form.get("temp_alert_threshold"),
                DEFAULT_TEMP_ALERT_THRESHOLD,
                minimum=1,
                maximum=150,
            ),
            "refresh_seconds": _to_int(
                request.form.get("refresh_seconds"),
                DEFAULT_REFRESH_SECONDS,
                minimum=3,
                maximum=3600,
            ),
            "offline_after_seconds": _to_int(
                request.form.get("offline_after_seconds"),
                DEFAULT_OFFLINE_AFTER_SECONDS,
                minimum=10,
                maximum=86400,
            ),
            "max_top_processes": _to_int(
                request.form.get("max_top_processes"),
                DEFAULT_MAX_TOP_PROCESSES,
                minimum=1,
                maximum=100,
            ),
            "discord_webhook_url": _clean_text(
                request.form.get("discord_webhook_url"),
                "",
            ),
            "notification_email_to": _clean_text(
                request.form.get("notification_email_to"),
                "",
            ),
            "smtp_host": _clean_text(
                request.form.get("smtp_host"),
                "",
            ),
            "smtp_port": _to_int(
                request.form.get("smtp_port"),
                "587",
                minimum=1,
                maximum=65535,
            ),
            "smtp_username": _clean_text(
                request.form.get("smtp_username"),
                "",
            ),
            "smtp_password": str(request.form.get("smtp_password", "")),
            "smtp_use_tls": _checkbox_value(request.form, "smtp_use_tls"),
            "smtp_from": _clean_text(
                request.form.get("smtp_from"),
                "livewire@localhost",
            ) or "livewire@localhost",
            "enhanced_hwmon_enabled": lhm_enabled,
            "lhm_auto_install": lhm_auto_install,
            "lhm_auto_start": lhm_auto_start,
            "lhm_url": lhm_url,
            "lhm_install_dir": lhm_install_dir,
            "lhm_download_url": lhm_download_url,
            "lhm_expected_sha256": lhm_expected_sha256,
            "privacy_mode_enabled": privacy_mode_enabled,
        }

        conn = get_db()
        try:
            cur = conn.cursor()
            key_col, value_col, updated_at_col = _get_settings_columns(cur)

            if not key_col or not value_col:
                flash("Settings table schema could not be resolved.", "error")
                return redirect(url_for("settings.settings"))

            for key, value in updates.items():
                _save_setting(cur, key_col, value_col, updated_at_col, key, value)

            if form_action == "save_and_test":
                send_test_notification(cur)
                flash("Settings saved and test notification requested.", "success")
            else:
                flash("Settings saved successfully.", "success")

            conn.commit()
        except Exception as exc:
            conn.rollback()
            flash(f"Failed to save settings: {exc}", "error")
        finally:
            conn.close()

        return redirect(url_for("settings.settings"))

    settings_map = fetch_settings()

    settings_map["lhm_url"] = _clean_text(
        settings_map.get("lhm_url"),
        DEFAULT_LHM_URL,
    ) or DEFAULT_LHM_URL
    settings_map["lhm_install_dir"] = _clean_text(
        settings_map.get("lhm_install_dir"),
        DEFAULT_LHM_INSTALL_DIR,
    ) or DEFAULT_LHM_INSTALL_DIR
    settings_map["lhm_download_url"] = _clean_text(
        settings_map.get("lhm_download_url"),
        DEFAULT_LHM_DOWNLOAD_URL,
    ) or DEFAULT_LHM_DOWNLOAD_URL
    settings_map["lhm_expected_sha256"] = _clean_text(
        settings_map.get("lhm_expected_sha256"),
        "",
    )
    settings_map["privacy_mode_enabled"] = _clean_text(
        settings_map.get("privacy_mode_enabled"),
        "0",
    ) or "0"

    return render_template("settings.html", settings_map=settings_map)