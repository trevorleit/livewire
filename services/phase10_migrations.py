
from database import get_db, DEFAULT_SETTINGS

PHASE10_SETTINGS = {
    "notifications_enable_discord": "0",
    "notifications_enable_email": "0",
    "notify_on_alert_open": "1",
    "notify_on_alert_resolve": "1",
    "discord_webhook_url": "",
    "smtp_host": "",
    "smtp_port": "587",
    "smtp_username": "",
    "smtp_password": "",
    "smtp_from_email": "",
    "notification_recipient_emails": "",
}

def _ensure_column(cur, table_name, column_name, definition):
    existing_columns = {row["name"] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}
    if column_name not in existing_columns:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

def _seed_settings(cur):
    seed = dict(DEFAULT_SETTINGS)
    seed.update(PHASE10_SETTINGS)
    for key, value in seed.items():
        cur.execute("INSERT OR IGNORE INTO settings (setting_key, setting_value) VALUES (?, ?)", (key, value))

def init_phase10_migrations():
    conn = get_db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS remediation_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name TEXT,
        alert_type TEXT,
        machine_role TEXT,
        action_type TEXT,
        payload_json TEXT,
        cooldown_minutes INTEGER DEFAULT 30,
        auto_approve INTEGER DEFAULT 0,
        enabled INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS remediation_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_id INTEGER,
        machine_id INTEGER,
        alert_id INTEGER,
        status TEXT,
        action_taken TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS notification_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channel_type TEXT,
        destination TEXT,
        message TEXT,
        status TEXT,
        detail TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    _ensure_column(cur,"remote_commands","source","TEXT")
    _ensure_column(cur,"remote_commands","trigger_alert_id","INTEGER")

    _seed_settings(cur)

    conn.commit()
    conn.close()
