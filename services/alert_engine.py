from datetime import datetime, timezone
import time

from database import get_db
from services.notification_service import handle_alert_notification
from services.remediation_service import run_remediation_rules
from services.runtime_settings import get_runtime_settings


_LAST_STATUS_UPDATE_TS = 0.0


def _parse_last_seen(value):
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


def create_alert_if_missing(cur, machine_id, alert_type, severity, message, hostname=None):
    cur.execute(
        """
        SELECT id
        FROM alerts
        WHERE machine_id = ?
          AND alert_type = ?
          AND is_resolved = 0
        ORDER BY id DESC
        LIMIT 1
        """,
        (machine_id, alert_type),
    )
    existing = cur.fetchone()
    if existing:
        return existing["id"]

    cur.execute(
        """
        INSERT INTO alerts (
            machine_id,
            alert_type,
            severity,
            message,
            status,
            is_resolved,
            created_at,
            recorded_at
        )
        VALUES (?, ?, ?, ?, 'open', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
        """,
        (machine_id, alert_type, severity, message),
    )
    related_alert_id = cur.lastrowid

    handle_alert_notification(
        cur,
        related_alert_id=related_alert_id,
        machine_id=machine_id,
        hostname=hostname or f"machine-{machine_id}",
        alert_type=alert_type,
        severity=severity,
        message=message,
        event_type="opened",
    )

    run_remediation_rules(
        cur,
        related_alert_id=related_alert_id,
        machine_id=machine_id,
        hostname=hostname or f"machine-{machine_id}",
        alert_type=alert_type,
        severity=severity,
        message=message,
    )

    return related_alert_id


def resolve_alert(cur, machine_id, alert_type, hostname=None):
    cur.execute(
        """
        SELECT id, severity, message
        FROM alerts
        WHERE machine_id = ?
          AND alert_type = ?
          AND is_resolved = 0
        """,
        (machine_id, alert_type),
    )
    rows = cur.fetchall()
    if not rows:
        return

    cur.execute(
        """
        UPDATE alerts
        SET is_resolved = 1,
            status = 'resolved',
            resolved_at = CURRENT_TIMESTAMP
        WHERE machine_id = ?
          AND alert_type = ?
          AND is_resolved = 0
        """,
        (machine_id, alert_type),
    )

    for row in rows:
        handle_alert_notification(
            cur,
            related_alert_id=row["id"],
            machine_id=machine_id,
            hostname=hostname or f"machine-{machine_id}",
            alert_type=alert_type,
            severity=row["severity"],
            message=row["message"],
            event_type="resolved",
        )


def log_event(cur, machine_id, event_type, severity, message, source="system", extra_json=None):
    cur.execute(
        """
        INSERT INTO event_logs (
            machine_id,
            event_type,
            severity,
            message,
            source,
            extra_json
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (machine_id, event_type, severity, message, source, extra_json),
    )


def evaluate_threshold_alerts(cur, machine_id, hostname, cpu_percent, ram_percent, cpu_temp, drives, runtime_settings):
    if (cpu_percent or 0) >= runtime_settings["cpu_alert_threshold"]:
        create_alert_if_missing(
            cur,
            machine_id,
            "cpu_high",
            "warning",
            f"{hostname} CPU is at {round(cpu_percent or 0, 1)}%",
            hostname,
        )
    else:
        resolve_alert(cur, machine_id, "cpu_high", hostname)

    if (ram_percent or 0) >= runtime_settings["ram_alert_threshold"]:
        create_alert_if_missing(
            cur,
            machine_id,
            "ram_high",
            "warning",
            f"{hostname} RAM is at {round(ram_percent or 0, 1)}%",
            hostname,
        )
    else:
        resolve_alert(cur, machine_id, "ram_high", hostname)

    if cpu_temp is not None and (cpu_temp or 0) >= runtime_settings["temp_alert_threshold"]:
        create_alert_if_missing(
            cur,
            machine_id,
            "temp_high",
            "warning",
            f"{hostname} CPU temperature is {round(cpu_temp or 0, 1)}°C",
            hostname,
        )
    else:
        resolve_alert(cur, machine_id, "temp_high", hostname)

    active_disk_alert_types = set()

    for drive in drives:
        drive_label = drive.get("mountpoint") or drive.get("device") or "drive"
        alert_type = f"disk_high::{drive_label}"

        if (drive.get("percent_used") or 0) >= runtime_settings["disk_alert_threshold"]:
            active_disk_alert_types.add(alert_type)
            create_alert_if_missing(
                cur,
                machine_id,
                alert_type,
                "warning",
                f"{hostname} {drive_label} is at {round(drive.get('percent_used') or 0, 1)}% used",
                hostname,
            )
        else:
            resolve_alert(cur, machine_id, alert_type, hostname)

    cur.execute(
        """
        SELECT DISTINCT alert_type
        FROM alerts
        WHERE machine_id = ?
          AND alert_type LIKE 'disk_high::%'
          AND is_resolved = 0
        """,
        (machine_id,),
    )
    open_disk_alerts = cur.fetchall()

    for row in open_disk_alerts:
        if row["alert_type"] not in active_disk_alert_types:
            resolve_alert(cur, machine_id, row["alert_type"], hostname)


def evaluate_service_alerts(cur, machine_id, hostname, services):
    watched = [svc for svc in services if str(svc.get("status", "")).lower() != "running"]

    if watched:
        names = ", ".join(
            [
                svc.get("display_name") or svc.get("service_name") or "service"
                for svc in watched[:3]
            ]
        )
        create_alert_if_missing(
            cur,
            machine_id,
            "service_down",
            "warning",
            f"{hostname} has stopped services: {names}",
            hostname,
        )
    else:
        resolve_alert(cur, machine_id, "service_down", hostname)


def update_machine_statuses(force=False, min_interval_seconds=15):
    global _LAST_STATUS_UPDATE_TS

    now_ts = time.time()
    if not force and (now_ts - _LAST_STATUS_UPDATE_TS) < max(1, min_interval_seconds):
        return

    runtime_settings = get_runtime_settings()
    offline_after_seconds = runtime_settings["offline_after_seconds"]

    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute("SELECT id, hostname, last_seen, is_online FROM machines")
        rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        any_changes = False

        for row in rows:
            parsed_last_seen = _parse_last_seen(row["last_seen"])
            is_online = 0

            if parsed_last_seen:
                diff = (now - parsed_last_seen).total_seconds()
                if diff <= offline_after_seconds:
                    is_online = 1

            previous_online = int(row["is_online"] or 0)

            if previous_online != is_online:
                any_changes = True

                if is_online == 0:
                    log_event(
                        cur,
                        row["id"],
                        "machine_offline",
                        "critical",
                        f"{row['hostname']} is offline",
                    )
                else:
                    log_event(
                        cur,
                        row["id"],
                        "machine_online",
                        "info",
                        f"{row['hostname']} is back online",
                    )

                cur.execute(
                    """
                    UPDATE machines
                    SET is_online = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                    """,
                    (is_online, row["id"]),
                )

            if is_online == 0:
                create_alert_if_missing(
                    cur,
                    row["id"],
                    "machine_offline",
                    "critical",
                    f"{row['hostname']} is offline",
                    row["hostname"],
                )
            else:
                resolve_alert(cur, row["id"], "machine_offline", row["hostname"])

        conn.commit()
        _LAST_STATUS_UPDATE_TS = now_ts

    finally:
        conn.close()