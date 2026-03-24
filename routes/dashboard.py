from flask import Blueprint, render_template, request

from database import get_db
from services.dashboard_service import (
    attach_machine_activity,
    build_health_summary,
    build_incident_spotlight,
    build_role_breakdown,
    enrich_machines,
    filter_machines,
    get_latest_commands_by_machine,
    get_latest_events_by_machine,
    get_recent_commands,
    get_recent_events,
)
from services.helpers import (
    freshness_badge_class,
    freshness_label,
    freshness_state,
    get_runtime_settings,
)
from services.view_model_service import enrich_machine_list_gpu


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    db = get_db()
    cur = db.cursor()

    q = (request.args.get("q") or "").strip()
    status_filter = (request.args.get("status") or "all").strip().lower()
    role_filter = (request.args.get("role") or "all").strip().lower()

    cur.execute(
        """
        SELECT
            m.*,
            COALESCE((
                SELECT COUNT(*)
                FROM alerts a
                WHERE a.machine_id = m.id
                  AND COALESCE(a.status, 'open') = 'open'
            ), 0) AS open_alert_count,
            GROUP_CONCAT(DISTINCT mg.group_name) AS group_names
        FROM machines m
        LEFT JOIN machine_group_members mgm ON mgm.machine_id = m.id
        LEFT JOIN machine_groups mg ON mg.id = mgm.group_id
        GROUP BY m.id
        ORDER BY
            CASE WHEN m.is_online = 1 THEN 0 ELSE 1 END,
            COALESCE(m.display_name, m.hostname, '') COLLATE NOCASE ASC
        """
    )
    all_machines = cur.fetchall()
    all_machines_count = len(all_machines)

    machines = enrich_machine_list_gpu(all_machines)
    machines = enrich_machines(machines)

    machine_ids = [m["id"] for m in machines]
    latest_events = get_latest_events_by_machine(cur, machine_ids)
    latest_commands = get_latest_commands_by_machine(cur, machine_ids)
    machines = attach_machine_activity(machines, latest_events, latest_commands)

    filtered_machines = filter_machines(
        machines,
        search_text=q,
        status_filter=status_filter,
        role_filter=role_filter,
    )

    total_machines = len(filtered_machines)
    online_count = sum(1 for m in filtered_machines if m.get("is_online"))
    offline_count = total_machines - online_count
    open_alerts = sum(int(m.get("open_alert_count") or 0) for m in filtered_machines)

    role_breakdown = build_role_breakdown(machines)
    health_summary = build_health_summary(machines)
    incident_spotlight = build_incident_spotlight(machines, limit=4)

    recent_events = get_recent_events(cur, limit=8)
    recent_commands = get_recent_commands(cur, limit=8)

    runtime_settings = get_runtime_settings()
    freshness_fresh_seconds = runtime_settings.get("freshness_fresh_seconds", 90)
    freshness_aging_seconds = runtime_settings.get("freshness_aging_seconds", 300)

    scheduler = {
        "enabled_jobs": 0,
        "disabled_jobs": 0,
        "due_now": 0,
        "total_groups": 0,
    }

    try:
        cur.execute("SELECT COUNT(*) AS count FROM scheduled_jobs WHERE enabled = 1")
        row = cur.fetchone()
        scheduler["enabled_jobs"] = row["count"] if row else 0
    except Exception:
        pass

    try:
        cur.execute("SELECT COUNT(*) AS count FROM scheduled_jobs WHERE enabled = 0")
        row = cur.fetchone()
        scheduler["disabled_jobs"] = row["count"] if row else 0
    except Exception:
        pass

    try:
        cur.execute("SELECT COUNT(*) AS count FROM machine_groups")
        row = cur.fetchone()
        scheduler["total_groups"] = row["count"] if row else 0
    except Exception:
        pass

    try:
        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM scheduled_jobs
            WHERE enabled = 1
              AND next_run_at IS NOT NULL
              AND datetime(next_run_at) <= datetime('now')
            """
        )
        row = cur.fetchone()
        scheduler["due_now"] = row["count"] if row else 0
    except Exception:
        pass

    return render_template(
        "index.html",
        machines=filtered_machines,
        total_machines=total_machines,
        all_machines_count=all_machines_count,
        online_count=online_count,
        offline_count=offline_count,
        open_alerts=open_alerts,
        scheduler=scheduler,
        role_breakdown=role_breakdown,
        health_summary=health_summary,
        incident_spotlight=incident_spotlight,
        recent_events=recent_events,
        recent_commands=recent_commands,
        search_text=q,
        status_filter=status_filter,
        role_filter=role_filter,
        freshness_label=freshness_label,
        freshness_state=freshness_state,
        freshness_badge_class=freshness_badge_class,
        freshness_fresh_seconds=freshness_fresh_seconds,
        freshness_aging_seconds=freshness_aging_seconds,
    )