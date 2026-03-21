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
    "enhanced_hwmon_enabled": "0",
    "lhm_auto_install": "0",
    "lhm_auto_start": "0",
    "lhm_url": "http://127.0.0.1:8085/data.json",
    "lhm_install_dir": r"C:\ProgramData\LiveWire\LibreHardwareMonitor",
    "lhm_download_url": "",
    "lhm_expected_sha256": "",
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

    conn = sqlite3.connect(
        get_db_path(),
        timeout=30,
        check_same_thread=False,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
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


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    if not table_exists(conn, table_name):
        return False
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return any(row["name"] == column_name for row in rows)


def ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, definition: str) -> None:
    if table_exists(conn, table_name) and not column_exists(conn, table_name, column_name):
        conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


# -------------------------------------------------------------------
# Core LiveWire schema
# -------------------------------------------------------------------

def ensure_core_schema() -> None:
    conn = get_db_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                hostname TEXT UNIQUE NOT NULL,
                display_name TEXT,
                ip_address TEXT,
                os_name TEXT,
                current_user TEXT,
                is_online INTEGER NOT NULL DEFAULT 0,
                cpu_percent REAL DEFAULT 0,
                ram_percent REAL DEFAULT 0,
                ram_used INTEGER DEFAULT 0,
                ram_total INTEGER DEFAULT 0,
                disk_used INTEGER DEFAULT 0,
                disk_total INTEGER DEFAULT 0,
                disk_percent REAL DEFAULT 0,
                net_up_bps REAL DEFAULT 0,
                net_down_bps REAL DEFAULT 0,
                cpu_temp REAL,
                gpu_name TEXT,
                gpu_load REAL,
                gpu_temp REAL,
                gpu_mem_used_mb REAL,
                gpu_mem_total_mb REAL,
                uptime_seconds INTEGER DEFAULT 0,
                last_seen TEXT,
                updated_at TEXT,
                location TEXT,
                machine_role TEXT,
                notes TEXT
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                is_resolved INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                resolved_at TEXT,
                resolution_note TEXT,
                FOREIGN KEY(machine_id) REFERENCES machines(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS remote_commands (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                payload_json TEXT,
                status TEXT NOT NULL DEFAULT 'pending_approval',
                result_text TEXT,
                requested_by TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                approved_at TEXT,
                completed_at TEXT,
                source TEXT,
                trigger_alert_id INTEGER,
                scheduled_job_id INTEGER,
                FOREIGN KEY(machine_id) REFERENCES machines(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                cpu_percent REAL DEFAULT 0,
                ram_percent REAL DEFAULT 0,
                ram_used INTEGER DEFAULT 0,
                ram_total INTEGER DEFAULT 0,
                disk_used INTEGER DEFAULT 0,
                disk_total INTEGER DEFAULT 0,
                disk_percent REAL DEFAULT 0,
                net_up_bps REAL DEFAULT 0,
                net_down_bps REAL DEFAULT 0,
                net_sent INTEGER DEFAULT 0,
                net_recv INTEGER DEFAULT 0,
                disk_read_bytes INTEGER DEFAULT 0,
                disk_write_bytes INTEGER DEFAULT 0,
                cpu_temp REAL,
                current_user TEXT,
                uptime_seconds INTEGER DEFAULT 0,
                gpu_name TEXT,
                gpu_load REAL,
                gpu_temp REAL,
                gpu_mem_used_mb REAL,
                gpu_mem_total_mb REAL,
                gpu_json TEXT,
                FOREIGN KEY(machine_id) REFERENCES machines(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER,
                event_type TEXT,
                severity TEXT,
                message TEXT,
                source TEXT,
                extra_json TEXT,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(machine_id) REFERENCES machines(id)
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS machine_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name TEXT NOT NULL UNIQUE,
                description TEXT,
                color_hex TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS machine_group_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                machine_id INTEGER NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(group_id, machine_id),
                FOREIGN KEY(group_id) REFERENCES machine_groups(id) ON DELETE CASCADE,
                FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_name TEXT,
                description TEXT,
                target_type TEXT NOT NULL,
                target_id INTEGER NOT NULL,
                action_type TEXT NOT NULL,
                action_payload_json TEXT,
                interval_minutes INTEGER NOT NULL DEFAULT 60,
                enabled INTEGER NOT NULL DEFAULT 1,
                auto_approve INTEGER NOT NULL DEFAULT 0,
                only_when_online INTEGER NOT NULL DEFAULT 0,
                next_run_at TEXT,
                last_run_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scheduled_job_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL,
                status TEXT,
                summary_text TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(job_id) REFERENCES scheduled_jobs(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS drive_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                device TEXT,
                mountpoint TEXT,
                filesystem TEXT,
                total_bytes INTEGER DEFAULT 0,
                used_bytes INTEGER DEFAULT 0,
                free_bytes INTEGER DEFAULT 0,
                percent_used REAL DEFAULT 0,
                FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS interface_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                interface_name TEXT,
                is_up INTEGER DEFAULT 0,
                speed_mbps INTEGER DEFAULT 0,
                ip_address TEXT,
                up_bps REAL DEFAULT 0,
                down_bps REAL DEFAULT 0,
                mtu INTEGER DEFAULT 0,
                mac_address TEXT,
                bytes_sent INTEGER DEFAULT 0,
                bytes_recv INTEGER DEFAULT 0,
                FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS service_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                service_name TEXT,
                display_name TEXT,
                status TEXT,
                start_type TEXT,
                username TEXT,
                binpath TEXT,
                FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS process_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                pid INTEGER,
                process_name TEXT,
                cpu_percent REAL DEFAULT 0,
                memory_mb REAL DEFAULT 0,
                memory_percent REAL DEFAULT 0,
                category TEXT,
                FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS software_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                name TEXT NOT NULL,
                version TEXT,
                publisher TEXT,
                source TEXT,
                install_date TEXT,
                FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE
            )
            """
        )

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS inventory_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
                cpu_model TEXT,
                physical_cores INTEGER,
                logical_cores INTEGER,
                total_ram_bytes INTEGER DEFAULT 0,
                boot_time_epoch REAL,
                python_version TEXT,
                machine_arch TEXT,
                motherboard TEXT,
                FOREIGN KEY(machine_id) REFERENCES machines(id) ON DELETE CASCADE
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

        ensure_column(conn, "event_logs", "source", "TEXT")
        ensure_column(conn, "event_logs", "extra_json", "TEXT")

        ensure_column(conn, "remote_commands", "source", "TEXT")
        ensure_column(conn, "remote_commands", "trigger_alert_id", "INTEGER")
        ensure_column(conn, "remote_commands", "scheduled_job_id", "INTEGER")

        ensure_column(conn, "alerts", "status", "TEXT DEFAULT 'open'")
        ensure_column(conn, "alerts", "is_resolved", "INTEGER DEFAULT 0")
        ensure_column(conn, "alerts", "resolved_at", "TEXT")
        ensure_column(conn, "alerts", "resolution_note", "TEXT")

        ensure_column(conn, "machines", "updated_at", "TEXT")
        ensure_column(conn, "machines", "location", "TEXT")
        ensure_column(conn, "machines", "machine_role", "TEXT")
        ensure_column(conn, "machines", "notes", "TEXT")

        ensure_column(conn, "snapshots", "uptime_seconds", "INTEGER DEFAULT 0")
        ensure_column(conn, "snapshots", "gpu_name", "TEXT")
        ensure_column(conn, "snapshots", "gpu_load", "REAL")
        ensure_column(conn, "snapshots", "gpu_temp", "REAL")
        ensure_column(conn, "snapshots", "gpu_mem_used_mb", "REAL")
        ensure_column(conn, "snapshots", "gpu_mem_total_mb", "REAL")
        ensure_column(conn, "snapshots", "gpu_json", "TEXT")
        ensure_column(conn, "snapshots", "net_sent", "INTEGER DEFAULT 0")
        ensure_column(conn, "snapshots", "net_recv", "INTEGER DEFAULT 0")
        ensure_column(conn, "snapshots", "disk_read_bytes", "INTEGER DEFAULT 0")
        ensure_column(conn, "snapshots", "disk_write_bytes", "INTEGER DEFAULT 0")

        ensure_column(conn, "interface_snapshots", "mtu", "INTEGER DEFAULT 0")
        ensure_column(conn, "interface_snapshots", "mac_address", "TEXT")
        ensure_column(conn, "interface_snapshots", "bytes_sent", "INTEGER DEFAULT 0")
        ensure_column(conn, "interface_snapshots", "bytes_recv", "INTEGER DEFAULT 0")

        ensure_column(conn, "service_snapshots", "binpath", "TEXT")

        ensure_column(conn, "software_snapshots", "install_date", "TEXT")

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_machines_hostname ON machines(hostname)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_machine_status ON alerts(machine_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_alerts_machine_resolved ON alerts(machine_id, is_resolved)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_remote_commands_machine_status ON remote_commands(machine_id, status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_snapshots_machine_recorded ON snapshots(machine_id, recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_event_logs_machine_recorded ON event_logs(machine_id, recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_machine_groups_name ON machine_groups(group_name)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_machine_group_members_group ON machine_group_members(group_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_machine_group_members_machine ON machine_group_members(machine_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled_next_run ON scheduled_jobs(enabled, next_run_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_scheduled_job_runs_job_created ON scheduled_job_runs(job_id, created_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_drive_snapshots_machine_recorded ON drive_snapshots(machine_id, recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_interface_snapshots_machine_recorded ON interface_snapshots(machine_id, recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_service_snapshots_machine_recorded ON service_snapshots(machine_id, recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_process_snapshots_machine_recorded ON process_snapshots(machine_id, recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_software_snapshots_machine_recorded ON software_snapshots(machine_id, recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_inventory_snapshots_machine_recorded ON inventory_snapshots(machine_id, recorded_at)"
        )

        conn.commit()
    finally:
        conn.close()


# -------------------------------------------------------------------
# RC / notification schema
# -------------------------------------------------------------------

def ensure_rc_schema() -> None:
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
    ensure_core_schema()
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