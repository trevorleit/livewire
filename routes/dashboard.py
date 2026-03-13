from flask import Blueprint, render_template
from database import get_db
from services.alert_engine import update_machine_statuses
from services.query_service import get_dashboard_machines, get_open_alert_count

dashboard_bp = Blueprint("dashboard", __name__)

@dashboard_bp.route("/")
def index():
    update_machine_statuses()
    conn = get_db()
    cur = conn.cursor()
    machines = get_dashboard_machines(cur)
    open_alerts = get_open_alert_count(cur)
    total_machines = len(machines)
    online_count = sum(1 for machine in machines if machine["is_online"])
    offline_count = total_machines - online_count
    conn.close()
    return render_template(
        "index.html",
        machines=machines,
        total_machines=total_machines,
        online_count=online_count,
        offline_count=offline_count,
        open_alerts=open_alerts,
    )
