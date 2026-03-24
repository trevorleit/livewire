import os
import sys
import json
import shutil
import sqlite3
from datetime import datetime, UTC
from database import insert_notification_log


CANONICAL_NOTIFICATION_COLUMNS = [
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

CANONICAL_REMEDIATION_COLUMNS = [
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


def utc_now():
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


def utc_stamp():
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def get_db_path():
    """
    Usage:
      python migrations/normalize_rc_schema.py [path_to_db]

    If no DB path is provided, this script assumes:
      ../livewire.db
    relative to the migrations folder.
    """
    if len(sys.argv) > 1:
        return os.path.abspath(sys.argv[1])

    script_dir = os.path.dirname(os.path.abspath(__file__))
    default_path = os.path.abspath(os.path.join(script_dir, "..", "livewire.db"))
    return default_path


def connect(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn, table_name):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def get_columns(conn, table_name):
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return [row["name"] for row in rows]


def is_exact_shape(actual_columns, canonical_columns):
    return actual_columns == canonical_columns


def make_backup(db_path):
    timestamp = utc_stamp()
    backup_path = f"{db_path}.backup_{timestamp}"
    shutil.copy2(db_path, backup_path)
    print(f"[backup] Created backup: {backup_path}")
    return backup_path


def ensure_json_string(value):
    if value is None:
        return None
    if isinstance(value, str):
        try:
            json.loads(value)
            return value
        except Exception:
            return json.dumps({"raw": value})
    try:
        return json.dumps(value)
    except Exception:
        return json.dumps({"raw": str(value)})


def normalize_boolish(value, default=0):
    if value is None:
        return default
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, (int, float)):
        return 1 if value else 0
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "on", "enabled"):
        return 1
    if s in ("0", "false", "no", "n", "off", "disabled"):
        return 0
    return default


def normalize_int(value, default=None):
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except Exception:
        return default


def normalize_float(value, default=None):
    if value is None or value == "":
        return default
    try:
        return float(value)
    except Exception:
        return default


def first_present(row, *keys, default=None):
    for key in keys:
        if key in row.keys():
            value = row[key]
            if value is not None:
                return value
    return default


def rename_existing_table(conn, old_name):
    timestamp = utc_stamp()
    legacy_name = f"{old_name}_legacy_{timestamp}"
    conn.execute(f"ALTER TABLE {old_name} RENAME TO {legacy_name}")
    print(f"[rename] {old_name} -> {legacy_name}")
    return legacy_name


def create_notification_logs_table(conn, table_name="notification_logs"):
    conn.execute(f"""
        CREATE TABLE {table_name} (
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
    """)
    print(f"[create] Created {table_name}")


def create_remediation_rules_table(conn, table_name="remediation_rules"):
    conn.execute(f"""
        CREATE TABLE {table_name} (
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
    """)
    print(f"[create] Created {table_name}")


def migrate_notification_logs(conn):
    table_name = "notification_logs"

    if not table_exists(conn, table_name):
        print(f"[skip] {table_name} does not exist; creating canonical empty table")
        create_notification_logs_table(conn, table_name)
        return

    current_columns = get_columns(conn, table_name)
    if is_exact_shape(current_columns, CANONICAL_NOTIFICATION_COLUMNS):
        print(f"[ok] {table_name} already matches canonical shape")
        return

    legacy_name = rename_existing_table(conn, table_name)
    create_notification_logs_table(conn, table_name)

    rows = conn.execute(f"SELECT * FROM {legacy_name}").fetchall()
    inserted = 0

    for row in rows:
        created_at = first_present(
            row,
            "created_at",
            "created_at",
            "created_at",
            "timestamp",
            default=utc_now(),
        )

        notification_type = first_present(
            row,
            "notification_type",
            "type",
            "notification_type",
            "notification_type",
            default="unknown",
        )

        channel = first_present(
            row,
            "channel",
            "channel",
            default="unknown",
        )

        status = first_present(
            row,
            "status",
            "status",
            "state",
            default="unknown",
        )

        recipient = first_present(
            row,
            "recipient",
            "to_recipient",
            "destination",
            "target",
            default=None,
        )

        subject = first_present(
            row,
            "subject",
            "title",
            default=None,
        )

        message = first_present(
            row,
            "message",
            "body",
            "content",
            default=None,
        )

        related_alert_id = normalize_int(
            first_present(
                row,
                "related_alert_id",
                "related_alert_id",
                default=None,
            ),
            default=None,
        )

        related_rule_id = normalize_int(
            first_present(
                row,
                "related_rule_id",
                "related_rule_id",
                default=None,
            ),
            default=None,
        )

        details_json = ensure_json_string(
            first_present(
                row,
                "details_json",
                "payload_json",
                "details_json",
                "details_json",
                default=None,
            )
        )

        old_id = first_present(row, "id", default=None)

        insert_notification_log(
    notification_type=notification_type if "notification_type" in locals() else "alert",
    channel=channel if "channel" in locals() else "ui",
    status=status if "status" in locals() else "sent",
    recipient=recipient if "recipient" in locals() else None,
    subject=subject if "subject" in locals() else None,
    message=message if "message" in locals() else None,
    related_alert_id=related_alert_id if "related_alert_id" in locals() else None,
    related_rule_id=related_rule_id if "related_rule_id" in locals() else None,
    details=details if "details" in locals() else None,
)  # TODO verify removed SQL args: (old_id,
            str(created_at),
            str(notification_type),
            str(channel),
            str(status),
            recipient,
            subject,
            message,
            related_alert_id,
            related_rule_id,
            details_json,)
        inserted += 1

    print(f"[migrate] notification_logs: migrated {inserted} row(s)")


def migrate_remediation_rules(conn):
    table_name = "remediation_rules"

    if not table_exists(conn, table_name):
        print(f"[skip] {table_name} does not exist; creating canonical empty table")
        create_remediation_rules_table(conn, table_name)
        return

    current_columns = get_columns(conn, table_name)
    if is_exact_shape(current_columns, CANONICAL_REMEDIATION_COLUMNS):
        print(f"[ok] {table_name} already matches canonical shape")
        return

    legacy_name = rename_existing_table(conn, table_name)
    create_remediation_rules_table(conn, table_name)

    rows = conn.execute(f"SELECT * FROM {legacy_name}").fetchall()
    inserted = 0

    for row in rows:
        now = utc_now()

        name = first_present(row, "name", "name", default="Unnamed Rule")
        description = first_present(row, "description", "notes", default=None)

        enabled = normalize_boolish(
            first_present(row, "enabled", "enabled", default=1),
            default=1,
        )

        machine_role = first_present(row, "machine_role", "machine_role", default=None)

        trigger_type = first_present(
            row,
            "trigger_type",
            "trigger",
            default="metric_threshold",
        )

        severity = first_present(row, "severity", default=None)

        metric_name = first_present(
            row,
            "metric_name",
            "metric",
            default=None,
        )

        comparison_operator = first_present(
            row,
            "comparison_operator",
            "operator",
            default=None,
        )

        threshold_value = normalize_float(
            first_present(
                row,
                "threshold_value",
                "threshold",
                default=None,
            ),
            default=None,
        )

        cooldown_seconds = first_present(
            row,
            "cooldown_seconds",
            default=None,
        )

        if cooldown_seconds is None:
            cooldown_seconds = normalize_int(
                first_present(row, "cooldown_seconds", default=None),
                default=None,
            )
            if cooldown_seconds is not None:
                cooldown_seconds = cooldown_seconds * 60

        cooldown_seconds = normalize_int(cooldown_seconds, default=300)

        action_type = first_present(
            row,
            "action_type",
            "action",
            default="noop",
        )

        action_payload_json = ensure_json_string(
            first_present(
                row,
                "action_payload_json",
                "payload_json",
                "action_payload",
                default=None,
            )
        )

        auto_approve = normalize_boolish(
            first_present(row, "auto_approve", default=0),
            default=0,
        )

        created_at = first_present(
            row,
            "created_at",
            "created_at",
            default=now,
        )

        updated_at = first_present(
            row,
            "updated_at",
            "updated_at",
            default=created_at or now,
        )

        old_id = first_present(row, "id", default=None)

        conn.execute("""
            INSERT INTO remediation_rules (
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
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            old_id,
            str(name),
            description,
            enabled,
            machine_role,
            str(trigger_type),
            severity,
            metric_name,
            comparison_operator,
            threshold_value,
            cooldown_seconds,
            str(action_type),
            action_payload_json,
            auto_approve,
            str(created_at),
            str(updated_at),
        ))
        inserted += 1

    print(f"[migrate] remediation_rules: migrated {inserted} row(s)")


def print_table_shape(conn, table_name):
    if not table_exists(conn, table_name):
        print(f"[shape] {table_name}: <missing>")
        return
    cols = get_columns(conn, table_name)
    print(f"[shape] {table_name}: {cols}")


def main():
    db_path = get_db_path()

    if not os.path.exists(db_path):
        print(f"[error] Database not found: {db_path}")
        sys.exit(1)

    print(f"[start] Using database: {db_path}")
    make_backup(db_path)

    conn = connect(db_path)

    try:
        conn.execute("BEGIN")

        migrate_notification_logs(conn)
        migrate_remediation_rules(conn)

        conn.commit()
        print("[commit] Migration committed successfully")

        print_table_shape(conn, "notification_logs")
        print_table_shape(conn, "remediation_rules")

    except Exception as exc:
        conn.rollback()
        print(f"[rollback] Migration failed: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()