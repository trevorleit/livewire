from flask import Blueprint, render_template
from database import get_db
from services.alert_engine import update_machine_statuses

events_bp = Blueprint("events", __name__)

@events_bp.route("/events")
def events():
    update_machine_statuses()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT e.*, COALESCE(m.display_name, m.hostname) AS machine_label
        FROM event_logs e
        JOIN machines m ON m.id = e.machine_id
        ORDER BY e.recorded_at DESC, e.id DESC
        LIMIT 300
    """)
    rows = cur.fetchall()
    conn.close()
    return render_template("events.html", event_rows=rows)
