import os
import sqlite3
from config import DATABASE

DEFAULT_SETTINGS = {
    "cpu_alert_threshold": "90",
    "ram_alert_threshold": "90",
    "disk_alert_threshold": "90",
    "temp_alert_threshold": "85",
    "refresh_seconds": "10",
    "offline_after_seconds": "90",
    "max_top_processes": "8",
    "discord_webhook_url": "",
    "notification_email_to": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_use_tls": "1",
    "smtp_from": "livewire@localhost",
}


def get_db():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(cur, table_name, column_name, definition):
    existing_columns = {row["name"] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in existing_columns:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def seed_settings(cur):
    for key, value in DEFAULT_SETTINGS.items():
        cur.execute("INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES (?, ?)", (key, value))


SCHEMA_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS machines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        hostname TEXT UNIQUE NOT NULL,
        ip_address TEXT,
        os_name TEXT,
        last_seen TEXT,
        is_online INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        display_name TEXT,
        machine_role TEXT,
        location TEXT,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        cpu_percent REAL,
        ram_total INTEGER,
        ram_used INTEGER,
        ram_percent REAL,
        disk_total INTEGER,
        disk_used INTEGER,
        disk_percent REAL,
        uptime_seconds INTEGER,
        current_user TEXT,
        net_sent INTEGER,
        net_recv INTEGER,
        cpu_temp REAL,
        disk_read_bytes INTEGER,
        disk_write_bytes INTEGER,
        net_up_bps REAL,
        net_down_bps REAL,
        gpu_name TEXT,
        gpu_load REAL,
        gpu_mem_used_mb REAL,
        gpu_mem_total_mb REAL,
        gpu_temp REAL,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS alerts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        alert_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        message TEXT NOT NULL,
        is_resolved INTEGER DEFAULT 0,
        resolved_at TEXT,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS event_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        event_type TEXT,
        severity TEXT,
        message TEXT,
        source TEXT,
        extra_json TEXT,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS drive_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        device TEXT,
        mountpoint TEXT,
        filesystem TEXT,
        total_bytes INTEGER,
        used_bytes INTEGER,
        free_bytes INTEGER,
        percent_used REAL,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS process_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        category TEXT,
        pid INTEGER,
        process_name TEXT,
        cpu_percent REAL,
        memory_percent REAL,
        memory_mb REAL,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
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
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS interface_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        interface_name TEXT,
        is_up INTEGER,
        speed_mbps REAL,
        mtu INTEGER,
        ip_address TEXT,
        mac_address TEXT,
        bytes_sent INTEGER,
        bytes_recv INTEGER,
        up_bps REAL,
        down_bps REAL,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS inventory_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        cpu_model TEXT,
        physical_cores INTEGER,
        logical_cores INTEGER,
        total_ram_bytes INTEGER,
        boot_time_epoch REAL,
        python_version TEXT,
        machine_arch TEXT,
        motherboard TEXT,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS software_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        recorded_at TEXT DEFAULT CURRENT_TIMESTAMP,
        source TEXT,
        name TEXT,
        version TEXT,
        publisher TEXT,
        install_date TEXT,
        FOREIGN KEY(machine_id) REFERENCES machines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS remote_commands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER NOT NULL,
        action_type TEXT NOT NULL,
        payload_json TEXT,
        status TEXT NOT NULL DEFAULT 'pending_approval',
        requested_by TEXT,
        result_text TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        approved_at TEXT,
        sent_at TEXT,
        completed_at TEXT,
        source TEXT,
        trigger_alert_id INTEGER,
        FOREIGN KEY(machine_id) REFERENCES machines(id),
        FOREIGN KEY(trigger_alert_id) REFERENCES alerts(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        setting_key TEXT UNIQUE NOT NULL,
        setting_value TEXT NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS remediation_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name TEXT NOT NULL,
        is_enabled INTEGER DEFAULT 1,
        alert_type TEXT NOT NULL,
        severity_filter TEXT DEFAULT 'any',
        action_type TEXT NOT NULL,
        payload_json TEXT,
        cooldown_minutes INTEGER DEFAULT 30,
        auto_approve INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS remediation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER NOT NULL,
        alert_id INTEGER NOT NULL,
        machine_id INTEGER NOT NULL,
        command_id INTEGER,
        status TEXT NOT NULL,
        message TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(rule_id) REFERENCES remediation_rules(id),
        FOREIGN KEY(alert_id) REFERENCES alerts(id),
        FOREIGN KEY(machine_id) REFERENCES machines(id),
        FOREIGN KEY(command_id) REFERENCES remote_commands(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS notification_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id INTEGER,
        alert_id INTEGER,
        channel TEXT NOT NULL,
        event_type TEXT NOT NULL,
        title TEXT,
        message TEXT,
        delivery_status TEXT NOT NULL,
        response_text TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(machine_id) REFERENCES machines(id),
        FOREIGN KEY(alert_id) REFERENCES alerts(id)
    )
    """,
]


def init_db():
    conn = get_db()
    cur = conn.cursor()

    for statement in SCHEMA_STATEMENTS:
        cur.execute(statement)

    ensure_column(cur, "machines", "display_name", "TEXT")
    ensure_column(cur, "machines", "machine_role", "TEXT")
    ensure_column(cur, "machines", "location", "TEXT")
    ensure_column(cur, "machines", "notes", "TEXT")
    ensure_column(cur, "remote_commands", "source", "TEXT")
    ensure_column(cur, "remote_commands", "trigger_alert_id", "INTEGER")

    seed_settings(cur)
    conn.commit()
    conn.close()
