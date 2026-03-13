from datetime import datetime, timezone
from database import get_db
from services.runtime_settings import get_runtime_settings

def create_alert_if_missing(cur, machine_id, alert_type, severity, message):
    cur.execute(
        "SELECT id FROM alerts WHERE machine_id = ? AND alert_type = ? AND is_resolved = 0 ORDER BY id DESC LIMIT 1",
        (machine_id, alert_type),
    )
    existing = cur.fetchone()
    if not existing:
        cur.execute(
            "INSERT INTO alerts (machine_id, alert_type, severity, message) VALUES (?, ?, ?, ?)",
            (machine_id, alert_type, severity, message),
        )

def resolve_alert(cur, machine_id, alert_type):
    cur.execute(
        "UPDATE alerts SET is_resolved = 1, resolved_at = CURRENT_TIMESTAMP WHERE machine_id = ? AND alert_type = ? AND is_resolved = 0",
        (machine_id, alert_type),
    )

def log_event(cur, machine_id, event_type, severity, message, source="system", extra_json=None):
    cur.execute(
        "INSERT INTO event_logs (machine_id, event_type, severity, message, source, extra_json) VALUES (?, ?, ?, ?, ?, ?)",
        (machine_id, event_type, severity, message, source, extra_json),
    )

def evaluate_threshold_alerts(cur, machine_id, hostname, cpu_percent, ram_percent, cpu_temp, drives, runtime_settings):
    if (cpu_percent or 0) >= runtime_settings["cpu_alert_threshold"]:
        create_alert_if_missing(cur, machine_id, "cpu_high", "warning", f"{hostname} CPU is at {round(cpu_percent or 0, 1)}%")
    else:
        resolve_alert(cur, machine_id, "cpu_high")

    if (ram_percent or 0) >= runtime_settings["ram_alert_threshold"]:
        create_alert_if_missing(cur, machine_id, "ram_high", "warning", f"{hostname} RAM is at {round(ram_percent or 0, 1)}%")
    else:
        resolve_alert(cur, machine_id, "ram_high")

    if cpu_temp is not None and (cpu_temp or 0) >= runtime_settings["temp_alert_threshold"]:
        create_alert_if_missing(cur, machine_id, "temp_high", "warning", f"{hostname} CPU temperature is {round(cpu_temp or 0, 1)}°C")
    else:
        resolve_alert(cur, machine_id, "temp_high")

    any_disk_alert = False
    for drive in drives:
        drive_label = drive.get("mountpoint") or drive.get("device") or "drive"
        alert_type = f"disk_high::{drive_label}"
        if (drive.get("percent_used") or 0) >= runtime_settings["disk_alert_threshold"]:
            any_disk_alert = True
            create_alert_if_missing(cur, machine_id, alert_type, "warning", f"{hostname} {drive_label} is at {round(drive.get('percent_used') or 0, 1)}% used")
        else:
            resolve_alert(cur, machine_id, alert_type)

    if not any_disk_alert:
        cur.execute("UPDATE alerts SET is_resolved = 1, resolved_at = CURRENT_TIMESTAMP WHERE machine_id = ? AND alert_type LIKE 'disk_high::%' AND is_resolved = 0", (machine_id,))

def evaluate_service_alerts(cur, machine_id, hostname, services):
    watched = [svc for svc in services if str(svc.get("status", "")).lower() != "running"]
    if watched:
        names = ", ".join([(svc.get("display_name") or svc.get("service_name") or "service") for svc in watched[:3]])
        create_alert_if_missing(cur, machine_id, "service_down", "warning", f"{hostname} has stopped services: {names}")
    else:
        resolve_alert(cur, machine_id, "service_down")

def update_machine_statuses():
    runtime_settings = get_runtime_settings()
    offline_after_seconds = runtime_settings["offline_after_seconds"]

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, hostname, last_seen, is_online FROM machines")
    rows = cur.fetchall()
    now = datetime.now(timezone.utc)

    for row in rows:
        is_online = 0
        if row["last_seen"]:
            try:
                last_seen = datetime.fromisoformat(row["last_seen"])
                diff = (now - last_seen).total_seconds()
                if diff <= offline_after_seconds:
                    is_online = 1
            except Exception:
                pass

        if row["is_online"] != is_online:
            if is_online == 0:
                log_event(cur, row["id"], "machine_offline", "critical", f"{row['hostname']} is offline")
            else:
                log_event(cur, row["id"], "machine_online", "info", f"{row['hostname']} is back online")

        cur.execute("UPDATE machines SET is_online = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (is_online, row["id"]))

        if is_online == 0:
            create_alert_if_missing(cur, row["id"], "machine_offline", "critical", f"{row['hostname']} is offline")
        else:
            resolve_alert(cur, row["id"], "machine_offline")

    conn.commit()
    conn.close()
