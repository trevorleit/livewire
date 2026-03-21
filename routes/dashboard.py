from flask import Blueprint, render_template

from database import get_db
from services.alert_engine import update_machine_statuses
from services.query_service import get_dashboard_machines, get_open_alert_count
from services.scheduler_service import get_scheduler_overview
from services.runtime_settings import get_runtime_settings
from services.view_model_service import enrich_machine_list_gpu


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/")
def index():
    update_machine_statuses()
    runtime_settings = get_runtime_settings()

    conn = get_db()
    try:
        cur = conn.cursor()

        machines = enrich_machine_list_gpu(get_dashboard_machines(cur))
        open_alerts = get_open_alert_count(cur)
        scheduler = get_scheduler_overview(cur)

        total_machines = len(machines)
        online_count = sum(1 for m in machines if m["is_online"])
        offline_count = total_machines - online_count

        cur.execute(
            """
            SELECT rc.*, COALESCE(m.display_name, m.hostname) AS machine_label
            FROM remote_commands rc
            JOIN machines m ON m.id = rc.machine_id
            ORDER BY rc.created_at DESC, rc.id DESC
            LIMIT 8
            """
        )
        recent_commands = cur.fetchall()

        cur.execute(
            """
            SELECT e.*, COALESCE(m.display_name, m.hostname) AS machine_label
            FROM event_logs e
            LEFT JOIN machines m ON m.id = e.machine_id
            ORDER BY e.recorded_at DESC, e.id DESC
            LIMIT 8
            """
        )
        recent_events = cur.fetchall()

    finally:
        conn.close()

    offline_after_seconds = int(runtime_settings.get("offline_after_seconds", 90) or 90)
    freshness_fresh_seconds = max(30, offline_after_seconds)
    freshness_aging_seconds = max(freshness_fresh_seconds + 30, offline_after_seconds * 2)

    return render_template(
        "index.html",
        machines=machines,
        total_machines=total_machines,
        online_count=online_count,
        offline_count=offline_count,
        open_alerts=open_alerts,
        scheduler=scheduler,
        recent_commands=recent_commands,
        recent_events=recent_events,
        offline_after_seconds=offline_after_seconds,
        freshness_fresh_seconds=freshness_fresh_seconds,
        freshness_aging_seconds=freshness_aging_seconds,
    )