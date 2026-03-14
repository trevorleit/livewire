from collections import Counter


def _normalize_text(value):
    return (value or "").strip().lower()


def calculate_machine_health(machine):
    open_alerts = int(machine["open_alert_count"] or 0)
    cpu = float(machine["cpu_percent"] or 0)
    ram = float(machine["ram_percent"] or 0)
    disk = float(machine["disk_percent"] or 0)
    temp = machine["cpu_temp"]
    temp = None if temp is None else float(temp)

    score = 100
    if not machine["is_online"]:
        score = 0
    else:
        score -= min(open_alerts * 18, 54)
        if cpu >= 95:
            score -= 18
        elif cpu >= 85:
            score -= 10
        elif cpu >= 70:
            score -= 4

        if ram >= 95:
            score -= 16
        elif ram >= 85:
            score -= 9
        elif ram >= 70:
            score -= 4

        if disk >= 95:
            score -= 18
        elif disk >= 85:
            score -= 10
        elif disk >= 70:
            score -= 4

        if temp is not None:
            if temp >= 90:
                score -= 14
            elif temp >= 80:
                score -= 8
            elif temp >= 70:
                score -= 3

    score = max(0, min(int(round(score)), 100))

    if not machine["is_online"]:
        health = "offline"
    elif open_alerts >= 2 or score < 45:
        health = "critical"
    elif open_alerts >= 1 or score < 75:
        health = "warning"
    else:
        health = "healthy"

    return score, health


def enrich_machines(machines):
    enriched = []
    for machine in machines:
        item = dict(machine)
        score, health = calculate_machine_health(machine)
        item["health_score"] = score
        item["health_status"] = health
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
    for machine in machines:
        label = (machine.get("machine_role") or "Unassigned").strip() or "Unassigned"
        counter[label] += 1
    return [{"role": role, "count": count} for role, count in sorted(counter.items(), key=lambda x: (-x[1], x[0].lower()))]


def build_health_summary(machines):
    summary = {"healthy": 0, "warning": 0, "critical": 0, "offline": 0}
    for machine in machines:
        summary[machine["health_status"]] = summary.get(machine["health_status"], 0) + 1
    return summary


def get_recent_events(cur, limit=8):
    cur.execute(
        """
        SELECT e.*, COALESCE(m.display_name, m.hostname) AS machine_label
        FROM event_logs e
        JOIN machines m ON m.id = e.machine_id
        ORDER BY e.recorded_at DESC, e.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cur.fetchall()


def get_recent_commands(cur, limit=8):
    cur.execute(
        """
        SELECT rc.*, COALESCE(m.display_name, m.hostname) AS machine_label
        FROM remote_commands rc
        JOIN machines m ON m.id = rc.machine_id
        ORDER BY rc.created_at DESC, rc.id DESC
        LIMIT ?
        """,
        (limit,),
    )
    return cur.fetchall()
