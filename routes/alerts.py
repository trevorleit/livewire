from flask import Blueprint, render_template, request

from database import get_db
from services.alert_engine import update_machine_statuses


alerts_bp = Blueprint("alerts", __name__)


def _table_columns(cur, table_name):
    return {row["name"] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}


@alerts_bp.route("/alerts")
def alerts():
    update_machine_statuses()

    status_filter = (request.args.get("status") or "all").strip().lower()
    severity_filter = (request.args.get("severity") or "all").strip().lower()
    machine_filter = (request.args.get("machine") or "").strip()
    type_filter = (request.args.get("type") or "").strip()
    q = (request.args.get("q") or "").strip()

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

        where_clauses = []
        params = []

        if status_filter == "open":
            where_clauses.append("COALESCE(a.is_resolved, 0) = 0")
        elif status_filter == "resolved":
            where_clauses.append("COALESCE(a.is_resolved, 0) = 1")

        if severity_filter in {"critical", "warning", "info"}:
            where_clauses.append("LOWER(COALESCE(a.severity, 'warning')) = ?")
            params.append(severity_filter)

        if machine_filter:
            where_clauses.append(
                """
                (
                    LOWER(COALESCE(m.display_name, '')) LIKE ?
                    OR LOWER(COALESCE(m.hostname, '')) LIKE ?
                )
                """
            )
            machine_like = f"%{machine_filter.lower()}%"
            params.extend([machine_like, machine_like])

        if type_filter:
            where_clauses.append("LOWER(COALESCE(a.alert_type, '')) LIKE ?")
            params.append(f"%{type_filter.lower()}%")

        if q:
            where_clauses.append(
                """
                (
                    LOWER(COALESCE(a.message, '')) LIKE ?
                    OR LOWER(COALESCE(a.alert_type, '')) LIKE ?
                    OR LOWER(COALESCE(m.display_name, '')) LIKE ?
                    OR LOWER(COALESCE(m.hostname, '')) LIKE ?
                )
                """
            )
            search_like = f"%{q.lower()}%"
            params.extend([search_like, search_like, search_like, search_like])

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

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
            {where_sql}
            ORDER BY COALESCE(a.is_resolved, 0) ASC, a.recorded_at DESC, a.id DESC
            LIMIT 200
        """

        cur.execute(sql, params)
        alert_rows = cur.fetchall()

        cur.execute(
            """
            SELECT DISTINCT COALESCE(display_name, hostname) AS machine_label
            FROM machines
            WHERE COALESCE(display_name, hostname) IS NOT NULL
            ORDER BY COALESCE(display_name, hostname) COLLATE NOCASE ASC
            """
        )
        machine_options = [row["machine_label"] for row in cur.fetchall() if row["machine_label"]]

        cur.execute(
            """
            SELECT DISTINCT alert_type
            FROM alerts
            WHERE alert_type IS NOT NULL
              AND TRIM(alert_type) <> ''
            ORDER BY alert_type COLLATE NOCASE ASC
            """
        )
        type_options = [row["alert_type"] for row in cur.fetchall() if row["alert_type"]]

    finally:
        conn.close()

    return render_template(
        "alerts.html",
        alert_rows=alert_rows,
        machine_options=machine_options,
        type_options=type_options,
        status_filter=status_filter,
        severity_filter=severity_filter,
        machine_filter=machine_filter,
        type_filter=type_filter,
        search_text=q,
    )