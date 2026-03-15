from flask import Blueprint, render_template

from database import get_db
from services.alert_engine import update_machine_statuses


alerts_bp = Blueprint("alerts", __name__)


def _table_columns(cur, table_name):
    return {row["name"] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}


@alerts_bp.route("/alerts")
def alerts():
    update_machine_statuses()

    conn = get_db()
    try:
        cur = conn.cursor()

        remediation_run_cols = _table_columns(cur, "remediation_runs")

        if "related_alert_id" in remediation_run_cols:
            remediation_count_sql = """
                (
                    SELECT COUNT(*)
                    FROM remediation_runs rr
                    WHERE rr.related_alert_id = a.id
                      AND rr.status = 'queued'
                ) AS remediation_count
            """
        elif "trigger_alert_id" in remediation_run_cols:
            remediation_count_sql = """
                (
                    SELECT COUNT(*)
                    FROM remediation_runs rr
                    WHERE rr.trigger_alert_id = a.id
                      AND rr.status = 'queued'
                ) AS remediation_count
            """
        elif "alert_id" in remediation_run_cols:
            remediation_count_sql = """
                (
                    SELECT COUNT(*)
                    FROM remediation_runs rr
                    WHERE rr.alert_id = a.id
                      AND rr.status = 'queued'
                ) AS remediation_count
            """
        else:
            remediation_count_sql = "0 AS remediation_count"

        sql = f"""
            SELECT
                a.*,
                m.hostname,
                COALESCE(m.display_name, m.hostname) AS machine_label,
                (
                    SELECT COUNT(*)
                    FROM notification_logs nl
                    WHERE nl.related_alert_id = a.id
                      AND nl.status = 'sent'
                ) AS sent_notification_count,
                {remediation_count_sql}
            FROM alerts a
            JOIN machines m ON m.id = a.machine_id
            ORDER BY a.is_resolved ASC, a.recorded_at DESC, a.id DESC
            LIMIT 200
        """

        cur.execute(sql)
        alert_rows = cur.fetchall()
    finally:
        conn.close()

    return render_template("alerts.html", alert_rows=alert_rows)