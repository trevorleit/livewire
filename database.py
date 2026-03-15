import json
import os
import sqlite3
from datetime import datetime, UTC
from typing import Any, Dict, List, Optional


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "instance", "dashboard.db")

DEFAULT_SETTINGS = {
    "refresh_seconds": 10,
    "max_top_processes": 10,
    "notify_on_alert_open": True,
    "notify_on_alert_resolve": True,
    "notifications_enable_discord": False,
    "discord_webhook_url": "",
    "cpu_alert_threshold": 90,
    "ram_alert_threshold": 90,
    "disk_alert_threshold": 90,
    "cpu_temp_alert_threshold": 85,
}


NOTIFICATION_LOG_COLUMNS = [
    "id",
    "created_at",
    "notification_type",
    "channel",
    "status",
    "recipient",
    "subject",
    "message",
    "related_alert_id",
    "related_rule_id",
    "details_json",
]

REMEDIATION_RULE_COLUMNS = [
    "id",
    "name",
    "description",
    "enabled",
    "machine_role",
    "trigger_type",
    "severity",
    "metric_name",
    "comparison_operator",
    "threshold_value",
    "cooldown_seconds",
    "action_type",
    "action_payload_json",
    "auto_approve",
    "created_at",
    "updated_at",
]


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def get_db_path() -> str:
    return os.environ.get("LIVEWIRE_DB_PATH", DEFAULT_DB_PATH)


def get_db_connection() -> sqlite3.Connection:
    db_dir = os.path.dirname(get_db_path())
    os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> sqlite3.Connection:
    return get_db_connection()


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: List[sqlite3.Row]) -> List[Dict[str, Any]]:
    return [row_to_dict(r) for r in rows if r is not None]


def parse_json_field(value: Optional[str], default=None):
    if value is None or value == "":
        return {} if default is None else default
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def dump_json_field(value: Any) -> Optional[str]:
    if value is None:
        return None
    return json.dumps(value)


def normalize_bool(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "y", "on", "enabled"):
        return 1
    if text in ("0", "false", "no", "n", "off", "disabled"):
        return 0
    return default


def normalize_int(value: Any, default=None):
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def normalize_float(value: Any, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except Exception:
        return default


def ensure_rc_schema() -> None:
    """
    Ensures the canonical RC tables exist.
    Also tolerates legacy settings table column names.
    """
    conn = get_db_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                notification_type TEXT NOT NULL,
                channel TEXT NOT NULL,
                status TEXT NOT NULL,
                recipient TEXT,
                subject TEXT,
                message TEXT,
                related_alert_id INTEGER,
                related_rule_id INTEGER,
                details_json TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS remediation_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                description TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                machine_role TEXT,
                trigger_type TEXT NOT NULL,
                severity TEXT,
                metric_name TEXT,
                comparison_operator TEXT,
                threshold_value REAL,
                cooldown_seconds INTEGER NOT NULL DEFAULT 300,
                action_type TEXT NOT NULL,
                action_payload_json TEXT,
                auto_approve INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
            """
        )

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notification_logs_created_at ON notification_logs(created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notification_logs_alert_rule ON notification_logs(related_alert_id, related_rule_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_remediation_rules_enabled ON remediation_rules(enabled)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_remediation_rules_trigger ON remediation_rules(trigger_type, severity, metric_name)"
        )

        # Detect actual settings table column names
        settings_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(settings)").fetchall()
        }

        if "key" in settings_cols and "value" in settings_cols:
            key_col = "key"
            value_col = "value"
        elif "setting_key" in settings_cols and "setting_value" in settings_cols:
            key_col = "setting_key"
            value_col = "setting_value"
        else:
            key_col = None
            value_col = None

        if key_col and value_col:
            for setting_name, setting_value in DEFAULT_SETTINGS.items():
                existing = conn.execute(
                    f"SELECT {key_col} FROM settings WHERE {key_col} = ?",
                    (setting_name,),
                ).fetchone()

                if not existing:
                    conn.execute(
                        f"INSERT INTO settings ({key_col}, {value_col}) VALUES (?, ?)",
                        (setting_name, json.dumps(setting_value)),
                    )

        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    ensure_rc_schema()


# -------------------------------------------------------------------
# Notification logs
# -------------------------------------------------------------------

def insert_notification_log(
    notification_type: str,
    channel: str,
    status: str,
    recipient: Optional[str] = None,
    subject: Optional[str] = None,
    message: Optional[str] = None,
    related_alert_id: Optional[int] = None,
    related_rule_id: Optional[int] = None,
    details: Optional[Dict[str, Any]] = None,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    owns_conn = conn is None
    conn = conn or get_db_connection()

    try:
        cur = conn.execute(
            """
            INSERT INTO notification_logs (
                created_at,
                notification_type,
                channel,
                status,
                recipient,
                subject,
                message,
                related_alert_id,
                related_rule_id,
                details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now(),
                notification_type,
                channel,
                status,
                recipient,
                subject,
                message,
                normalize_int(related_alert_id),
                normalize_int(related_rule_id),
                dump_json_field(details),
            ),
        )
        if owns_conn:
            conn.commit()
        return cur.lastrowid
    finally:
        if owns_conn:
            conn.close()


def get_notification_log(notification_log_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                created_at,
                notification_type,
                channel,
                status,
                recipient,
                subject,
                message,
                related_alert_id,
                related_rule_id,
                details_json
            FROM notification_logs
            WHERE id = ?
            """,
            (notification_log_id,),
        ).fetchone()

        data = row_to_dict(row)
        if not data:
            return None

        data["details"] = parse_json_field(data.get("details_json"), {})
        return data
    finally:
        conn.close()


def list_notification_logs(
    limit: int = 100,
    notification_type: Optional[str] = None,
    channel: Optional[str] = None,
    status: Optional[str] = None,
    related_alert_id: Optional[int] = None,
    related_rule_id: Optional[int] = None,
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        sql = """
            SELECT
                id,
                created_at,
                notification_type,
                channel,
                status,
                recipient,
                subject,
                message,
                related_alert_id,
                related_rule_id,
                details_json
            FROM notification_logs
            WHERE 1=1
        """
        params = []

        if notification_type:
            sql += " AND notification_type = ?"
            params.append(notification_type)
        if channel:
            sql += " AND channel = ?"
            params.append(channel)
        if status:
            sql += " AND status = ?"
            params.append(status)
        if related_alert_id is not None:
            sql += " AND related_alert_id = ?"
            params.append(related_alert_id)
        if related_rule_id is not None:
            sql += " AND related_rule_id = ?"
            params.append(related_rule_id)

        sql += " ORDER BY datetime(created_at) DESC, id DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        results = rows_to_dicts(rows)
        for item in results:
            item["details"] = parse_json_field(item.get("details_json"), {})
        return results
    finally:
        conn.close()


# -------------------------------------------------------------------
# Remediation rules
# -------------------------------------------------------------------

def insert_remediation_rule(
    name: str,
    trigger_type: str,
    action_type: str,
    description: Optional[str] = None,
    enabled: int = 1,
    machine_role: Optional[str] = None,
    severity: Optional[str] = None,
    metric_name: Optional[str] = None,
    comparison_operator: Optional[str] = None,
    threshold_value: Optional[float] = None,
    cooldown_seconds: int = 300,
    action_payload: Optional[Dict[str, Any]] = None,
    auto_approve: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> int:
    owns_conn = conn is None
    conn = conn or get_db_connection()

    try:
        now = utc_now()
        cur = conn.execute(
            """
            INSERT INTO remediation_rules (
                name,
                description,
                enabled,
                machine_role,
                trigger_type,
                severity,
                metric_name,
                comparison_operator,
                threshold_value,
                cooldown_seconds,
                action_type,
                action_payload_json,
                auto_approve,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip(),
                description.strip() if isinstance(description, str) and description.strip() else None,
                normalize_bool(enabled, 1),
                machine_role.strip() if isinstance(machine_role, str) and machine_role.strip() else None,
                trigger_type.strip(),
                severity.strip() if isinstance(severity, str) and severity.strip() else None,
                metric_name.strip() if isinstance(metric_name, str) and metric_name.strip() else None,
                comparison_operator.strip() if isinstance(comparison_operator, str) and comparison_operator.strip() else None,
                normalize_float(threshold_value),
                normalize_int(cooldown_seconds, 300),
                action_type.strip(),
                dump_json_field(action_payload),
                normalize_bool(auto_approve, 0),
                now,
                now,
            ),
        )
        if owns_conn:
            conn.commit()
        return cur.lastrowid
    finally:
        if owns_conn:
            conn.close()


def update_remediation_rule(
    rule_id: int,
    name: str,
    trigger_type: str,
    action_type: str,
    description: Optional[str] = None,
    enabled: int = 1,
    machine_role: Optional[str] = None,
    severity: Optional[str] = None,
    metric_name: Optional[str] = None,
    comparison_operator: Optional[str] = None,
    threshold_value: Optional[float] = None,
    cooldown_seconds: int = 300,
    action_payload: Optional[Dict[str, Any]] = None,
    auto_approve: int = 0,
    conn: Optional[sqlite3.Connection] = None,
) -> None:
    owns_conn = conn is None
    conn = conn or get_db_connection()

    try:
        conn.execute(
            """
            UPDATE remediation_rules
            SET
                name = ?,
                description = ?,
                enabled = ?,
                machine_role = ?,
                trigger_type = ?,
                severity = ?,
                metric_name = ?,
                comparison_operator = ?,
                threshold_value = ?,
                cooldown_seconds = ?,
                action_type = ?,
                action_payload_json = ?,
                auto_approve = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                name.strip(),
                description.strip() if isinstance(description, str) and description.strip() else None,
                normalize_bool(enabled, 1),
                machine_role.strip() if isinstance(machine_role, str) and machine_role.strip() else None,
                trigger_type.strip(),
                severity.strip() if isinstance(severity, str) and severity.strip() else None,
                metric_name.strip() if isinstance(metric_name, str) and metric_name.strip() else None,
                comparison_operator.strip() if isinstance(comparison_operator, str) and comparison_operator.strip() else None,
                normalize_float(threshold_value),
                normalize_int(cooldown_seconds, 300),
                action_type.strip(),
                dump_json_field(action_payload),
                normalize_bool(auto_approve, 0),
                utc_now(),
                rule_id,
            ),
        )
        if owns_conn:
            conn.commit()
    finally:
        if owns_conn:
            conn.close()


def get_remediation_rule(rule_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        row = conn.execute(
            """
            SELECT
                id,
                name,
                description,
                enabled,
                machine_role,
                trigger_type,
                severity,
                metric_name,
                comparison_operator,
                threshold_value,
                cooldown_seconds,
                action_type,
                action_payload_json,
                auto_approve,
                created_at,
                updated_at
            FROM remediation_rules
            WHERE id = ?
            """,
            (rule_id,),
        ).fetchone()

        data = row_to_dict(row)
        if not data:
            return None

        data["action_payload"] = parse_json_field(data.get("action_payload_json"), {})
        return data
    finally:
        conn.close()


def list_remediation_rules(
    enabled_only: bool = False,
    machine_role: Optional[str] = None,
    trigger_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    try:
        sql = """
            SELECT
                id,
                name,
                description,
                enabled,
                machine_role,
                trigger_type,
                severity,
                metric_name,
                comparison_operator,
                threshold_value,
                cooldown_seconds,
                action_type,
                action_payload_json,
                auto_approve,
                created_at,
                updated_at
            FROM remediation_rules
            WHERE 1=1
        """
        params = []

        if enabled_only:
            sql += " AND enabled = 1"
        if machine_role:
            sql += " AND machine_role = ?"
            params.append(machine_role)
        if trigger_type:
            sql += " AND trigger_type = ?"
            params.append(trigger_type)

        sql += " ORDER BY name ASC, id DESC"

        rows = conn.execute(sql, params).fetchall()
        results = rows_to_dicts(rows)
        for item in results:
            item["action_payload"] = parse_json_field(item.get("action_payload_json"), {})
        return results
    finally:
        conn.close()


def set_remediation_rule_enabled(rule_id: int, enabled: int) -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """
            UPDATE remediation_rules
            SET enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (normalize_bool(enabled, 1), utc_now(), rule_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_remediation_rule(rule_id: int) -> None:
    conn = get_db_connection()
    try:
        conn.execute("DELETE FROM remediation_rules WHERE id = ?", (rule_id,))
        conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------------
# Form mapping helpers
# -------------------------------------------------------------------

def remediation_rule_from_form(form) -> Dict[str, Any]:
    action_payload = {
        "service_name": (form.get("service_name") or "").strip() or None,
        "pid": normalize_int(form.get("pid")),
        "delay_seconds": normalize_int(form.get("delay_seconds")),
        "command_text": (form.get("command_text") or "").strip() or None,
    }

    action_payload = {k: v for k, v in action_payload.items() if v not in (None, "", [])}

    return {
        "name": (form.get("name") or "").strip(),
        "description": (form.get("description") or "").strip() or None,
        "enabled": 1 if form.get("enabled") else 0,
        "machine_role": (form.get("machine_role") or "").strip() or None,
        "trigger_type": (form.get("trigger_type") or "").strip(),
        "severity": (form.get("severity") or "").strip() or None,
        "metric_name": (form.get("metric_name") or "").strip() or None,
        "comparison_operator": (form.get("comparison_operator") or "").strip() or None,
        "threshold_value": normalize_float(form.get("threshold_value")),
        "cooldown_seconds": normalize_int(form.get("cooldown_seconds"), 300),
        "action_type": (form.get("action_type") or "").strip(),
        "action_payload": action_payload,
        "auto_approve": 1 if form.get("auto_approve") else 0,
    }


def validate_remediation_rule_payload(data: Dict[str, Any]) -> List[str]:
    errors = []

    if not data.get("name"):
        errors.append("Rule name is required.")
    if not data.get("trigger_type"):
        errors.append("Trigger type is required.")
    if not data.get("action_type"):
        errors.append("Action type is required.")

    trigger_type = data.get("trigger_type")
    if trigger_type == "metric_threshold":
        if not data.get("metric_name"):
            errors.append("Metric name is required for metric threshold rules.")
        if not data.get("comparison_operator"):
            errors.append("Comparison operator is required for metric threshold rules.")
        if data.get("threshold_value") is None:
            errors.append("Threshold value is required for metric threshold rules.")

    return errors