from flask import Blueprint, render_template
from database import get_db
from services.alert_engine import update_machine_statuses

alerts_bp = Blueprint("alerts", __name__)

@alerts_bp.route("/alerts")
def alerts():
    update_machine_statuses()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        SELECT a.*, m.hostname, COALESCE(m.display_name, m.hostname) AS machine_label
        FROM alerts a
        JOIN machines m ON m.id = a.machine_id
        ORDER BY a.is_resolved ASC, a.recorded_at DESC, a.id DESC
        LIMIT 200
    """)
    alert_rows = cur.fetchall()
    conn.close()
    return render_template("alerts.html", alert_rows=alert_rows)
