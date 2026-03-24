from collections import Counter

from services.helpers import format_last_seen


STATUS_CLASS_MAP = {
    "pending_approval": "pill-warning",
    "sent": "pill-warning",
    "queued": "pill-warning",
    "approved": "pill-info",
    "completed": "pill-online",
    "success": "pill-online",
    "failed": "pill-offline",
    "error": "pill-offline",
    "cancelled": "pill-muted",
    "canceled": "pill-muted",
    "expired": "pill-muted",
}

SEVERITY_CLASS_MAP = {
    "critical": "pill-offline",
    "error": "pill-offline",
    "warning": "pill-warning",
    "warn": "pill-warning",
    "info": "pill-info",
    "debug": "pill-muted",
}

SOURCE_CLASS_MAP = {
    "scheduler": "automation",
    "automation": "automation",
    "rule": "automation",
    "manual": "manual",
    "operator": "manual",
    "user": "manual",
    "system": "system",
    "agent": "system",
}

ACTION_LABELS = {
    "restart_service": "Restart Service",
    "stop_process": "Stop Process",
    "reboot_machine": "Reboot Machine",
    "run_script": "Run Script",
    "clear_temp": "Clear Temp",
    "refresh_policy": "Refresh Policy",
}

EVENT_LABELS = {
    "alert_opened": "Alert Opened",
    "alert_closed": "Alert Resolved",
    "command_created": "Command Created",
    "command_completed": "Command Completed",
    "command_failed": "Command Failed",
    "scheduler_tick": "Scheduler Tick",
    "remediation_executed": "Remediation Executed",
    "machine_online": "Machine Online",
    "machine_offline": "Machine Offline",
    "agent_checkin": "Agent Check-in",
}


def _normalize_text(value):
    return (value or "").strip().lower()


def _titleize_slug(value, default="Unknown"):
    text = (value or "").strip()
    if not text:
        return default
    return text.replace("_", " ").replace("-", " ").title()


def _compact_message(value, default="No details available."):
    text = (value or "").strip()
    if not text:
        return default
    return " ".join(text.split())


def _coerce_int(value, default=0):
    try:
        return int(value or 0)
    except Exception:
        return default


def _coerce_float(value, default=0.0):
    try:
        return float(value or 0)
    except Exception:
        return default


def _build_source_meta(raw_source):
    source_value = _normalize_text(raw_source or "manual") or "manual"
    source_kind = SOURCE_CLASS_MAP.get(source_value, "manual")
    source_label = _titleize_slug(source_value, default="Manual")
    return source_value, source_kind, source_label


def calculate_machine_health(machine):
    open_alerts = _coerce_int(machine.get("open_alert_count"))
    cpu = _coerce_float(machine.get("cpu_percent"))
    ram = _coerce_float(machine.get("ram_percent"))
    disk = _coerce_float(machine.get("disk_percent"))
    temp = machine.get("cpu_temp")
    temp = None if temp is None else _coerce_float(temp)

    score = 100
    flags = []

    if not machine.get("is_online"):
        score = 0
        flags.append("Offline")
    else:
        if open_alerts:
            flags.append(f"{open_alerts} open alert{'s' if open_alerts != 1 else ''}")
        score -= min(open_alerts * 18, 54)

        if cpu >= 95:
            score -= 18
            flags.append("CPU saturated")
        elif cpu >= 85:
            score -= 10
            flags.append("CPU elevated")
        elif cpu >= 70:
            score -= 4

        if ram >= 95:
            score -= 16
            flags.append("RAM saturated")
        elif ram >= 85:
            score -= 9
            flags.append("RAM elevated")
        elif ram >= 70:
            score -= 4

        if disk >= 95:
            score -= 18
            flags.append("Disk critical")
        elif disk >= 85:
            score -= 10
            flags.append("Disk elevated")
        elif disk >= 70:
            score -= 4

        if temp is not None:
            if temp >= 90:
                score -= 14
                flags.append("CPU temp critical")
            elif temp >= 80:
                score -= 8
                flags.append("CPU temp high")
            elif temp >= 70:
                score -= 3

    score = max(0, min(int(round(score)), 100))

    if not machine.get("is_online"):
        health = "offline"
    elif open_alerts >= 2 or score < 45:
        health = "critical"
    elif open_alerts >= 1 or score < 75:
        health = "warning"
    else:
        health = "healthy"

    return score, health, flags[:3]


def enrich_machines(machines):
    enriched = []
    for machine in machines:
        item = dict(machine)
        score, health, flags = calculate_machine_health(machine)
        item["health_score"] = score
        item["health_status"] = health
        item["health_flags"] = flags
        enriched.append(item)
    return enriched


def attach_machine_activity(machines, event_map=None, command_map=None):
    event_map = event_map or {}
    command_map = command_map or {}

    enriched = []
    for machine in machines:
        item = dict(machine)

        latest_event = event_map.get(machine.get("id"))
        latest_command = command_map.get(machine.get("id"))

        item["latest_event"] = latest_event
        item["latest_command"] = latest_command

        item["activity_event_label"] = latest_event.get("event_label") if latest_event else None
        item["activity_event_class"] = latest_event.get("severity_class") if latest_event else "pill-muted"
        item["activity_event_time_ago"] = latest_event.get("time_ago") if latest_event else None

        item["activity_command_label"] = latest_command.get("action_label") if latest_command else None
        item["activity_command_class"] = latest_command.get("status_class") if latest_command else "pill-muted"
        item["activity_command_status"] = latest_command.get("status_label") if latest_command else None
        item["activity_command_time_ago"] = latest_command.get("time_ago") if latest_command else None

        enriched.append(item)

    return enriched


def filter_machines(machines, search_text="", status_filter="all", role_filter="all"):
    search_text = _normalize_text(search_text)
    status_filter = _normalize_text(status_filter or "all")
    role_filter = _normalize_text(role_filter or "all")

    filtered = []
    for machine in machines:
        haystack = " ".join([
            str(machine.get("display_name") or ""),
            str(machine.get("hostname") or ""),
            str(machine.get("ip_address") or ""),
            str(machine.get("os_name") or ""),
            str(machine.get("location") or ""),
            str(machine.get("machine_role") or ""),
            str(machine.get("current_user") or ""),
            str(machine.get("group_names") or ""),
        ]).lower()

        if search_text and search_text not in haystack:
            continue

        if status_filter == "online" and not machine.get("is_online"):
            continue
        if status_filter == "offline" and machine.get("is_online"):
            continue
        if status_filter == "healthy" and machine.get("health_status") != "healthy":
            continue
        if status_filter == "warning" and machine.get("health_status") != "warning":
            continue
        if status_filter == "critical" and machine.get("health_status") != "critical":
            continue

        machine_role = _normalize_text(machine.get("machine_role") or "unassigned")
        if role_filter != "all" and machine_role != role_filter:
            continue

        filtered.append(machine)

    return filtered


def build_role_breakdown(machines):
    counter = Counter()
    total = len(machines)

    for machine in machines:
        label = (machine.get("machine_role") or "Unassigned").strip() or "Unassigned"
        counter[label] += 1

    rows = []
    for role, count in sorted(counter.items(), key=lambda x: (-x[1], x[0].lower())):
        percent = round((count / total) * 100, 1) if total else 0
        rows.append({
            "role": role,
            "count": count,
            "percent": percent,
        })

    return rows


def build_health_summary(machines):
    summary = {
        "healthy": 0,
        "warning": 0,
        "critical": 0,
        "offline": 0,
        "total": len(machines),
    }

    for machine in machines:
        key = machine.get("health_status") or "healthy"
        summary[key] = summary.get(key, 0) + 1

    total = summary["total"]
    summary["healthy_percent"] = round((summary["healthy"] / total) * 100, 1) if total else 0
    summary["warning_percent"] = round((summary["warning"] / total) * 100, 1) if total else 0
    summary["critical_percent"] = round((summary["critical"] / total) * 100, 1) if total else 0
    summary["offline_percent"] = round((summary["offline"] / total) * 100, 1) if total else 0
    return summary


def build_incident_spotlight(machines, limit=4):
    def score(machine):
        total = 0

        if not machine.get("is_online"):
            total += 100

        health = machine.get("health_status")
        if health == "critical":
            total += 60
        elif health == "warning":
            total += 30
        elif health == "offline":
            total += 80

        alerts = _coerce_int(machine.get("open_alert_count"))
        total += alerts * 10

        freshness = machine.get("last_seen")
        freshness_text = format_last_seen(freshness)
        if freshness_text == "Never":
            total += 20

        cpu = _coerce_float(machine.get("cpu_percent"))
        ram = _coerce_float(machine.get("ram_percent"))
        disk = _coerce_float(machine.get("disk_percent"))

        total += int(cpu / 10)
        total += int(ram / 10)
        total += int(disk / 10)

        return total

    ranked = sorted(machines, key=score, reverse=True)
    return [machine for machine in ranked if score(machine) > 0][:limit]


def _enrich_event_row(row):
    item = dict(row)
    severity = _normalize_text(item.get("severity") or "info") or "info"
    source_value, source_kind, source_label = _build_source_meta(item.get("source") or "system")

    item["event_label"] = EVENT_LABELS.get(
        item.get("event_type"),
        _titleize_slug(item.get("event_type"), default="Event"),
    )
    item["severity_value"] = severity
    item["severity_label"] = _titleize_slug(severity, default="Info")
    item["severity_class"] = SEVERITY_CLASS_MAP.get(severity, "pill-muted")
    item["source_value"] = source_value
    item["source_kind"] = source_kind
    item["source_label"] = source_label
    item["machine_label"] = item.get("machine_label") or "System"
    item["message"] = _compact_message(item.get("message"), default="No event details recorded.")
    item["time_ago"] = format_last_seen(item.get("recorded_at"))
    item["time_label"] = item.get("recorded_at") or "Unknown"
    return item


def _enrich_command_row(row):
    item = dict(row)
    status_value = _normalize_text(item.get("status") or "pending_approval") or "pending_approval"
    source_value, source_kind, source_label = _build_source_meta(
        item.get("source") or item.get("requested_by") or "manual"
    )

    action_type = item.get("action_type")
    item["action_label"] = ACTION_LABELS.get(action_type, _titleize_slug(action_type))
    item["status_value"] = status_value
    item["status_label"] = _titleize_slug(status_value, default="Pending Approval")
    item["status_class"] = STATUS_CLASS_MAP.get(status_value, "pill-muted")
    item["source_value"] = source_value
    item["source_kind"] = source_kind
    item["source_label"] = source_label
    item["machine_label"] = item.get("machine_label") or "Unknown Machine"
    item["result_preview"] = _compact_message(item.get("result_text"), default="No result recorded yet.")
    item["requested_by_label"] = item.get("requested_by") or "System"
    item["time_ago"] = format_last_seen(item.get("created_at"))
    item["time_label"] = item.get("created_at") or "Unknown"
    return item


def get_recent_events(cur, limit=8):
    cur.execute(
        """
        SELECT
            e.*,
            COALESCE(m.display_name, m.hostname, 'System') AS machine_label
        FROM event_logs e
        LEFT JOIN machines m ON m.id = e.machine_id
        ORDER BY e.recorded_at DESC, e.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_enrich_event_row(row) for row in cur.fetchall()]


def get_recent_commands(cur, limit=8):
    cur.execute(
        """
        SELECT
            rc.*,
            COALESCE(m.display_name, m.hostname, 'Unknown Machine') AS machine_label
        FROM remote_commands rc
        LEFT JOIN machines m ON m.id = rc.machine_id
        ORDER BY rc.created_at DESC, rc.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return [_enrich_command_row(row) for row in cur.fetchall()]


def get_latest_events_by_machine(cur, machine_ids):
    if not machine_ids:
        return {}

    placeholders = ",".join(["?"] * len(machine_ids))
    cur.execute(
        f"""
        SELECT
            e.*,
            COALESCE(m.display_name, m.hostname, 'System') AS machine_label
        FROM event_logs e
        LEFT JOIN machines m ON m.id = e.machine_id
        WHERE e.machine_id IN ({placeholders})
        ORDER BY e.recorded_at DESC, e.id DESC
        """,
        tuple(machine_ids),
    )

    latest = {}
    for row in cur.fetchall():
        machine_id = row["machine_id"]
        if machine_id not in latest:
            latest[machine_id] = _enrich_event_row(row)

    return latest


def get_latest_commands_by_machine(cur, machine_ids):
    if not machine_ids:
        return {}

    placeholders = ",".join(["?"] * len(machine_ids))
    cur.execute(
        f"""
        SELECT
            rc.*,
            COALESCE(m.display_name, m.hostname, 'Unknown Machine') AS machine_label
        FROM remote_commands rc
        LEFT JOIN machines m ON m.id = rc.machine_id
        WHERE rc.machine_id IN ({placeholders})
        ORDER BY rc.created_at DESC, rc.id DESC
        """,
        tuple(machine_ids),
    )

    latest = {}
    for row in cur.fetchall():
        machine_id = row["machine_id"]
        if machine_id not in latest:
            latest[machine_id] = _enrich_command_row(row)

    return latest