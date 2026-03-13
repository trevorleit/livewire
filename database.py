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

def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
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
        completed_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        setting_key TEXT UNIQUE NOT NULL,
        setting_value TEXT NOT NULL,
        updated_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)

    seed_settings(cur)
    conn.commit()
    conn.close()
