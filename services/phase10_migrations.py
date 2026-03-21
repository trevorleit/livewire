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


def _table_exists(cur, table_name):
    row = cur.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _ensure_column(cur, table_name, column_name, definition):
    if not _table_exists(cur, table_name):
        return

    existing_columns = {
        row["name"] for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing_columns:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _seed_settings(cur):
    if not _table_exists(cur, "settings"):
        return

    seed = dict(DEFAULT_SETTINGS)
    seed.update(PHASE10_SETTINGS)

    settings_cols = {
        row["name"] for row in cur.execute("PRAGMA table_info(settings)").fetchall()
    }

    if "key" in settings_cols and "value" in settings_cols:
        key_col = "key"
        value_col = "value"
    elif "setting_key" in settings_cols and "setting_value" in settings_cols:
        key_col = "setting_key"
        value_col = "setting_value"
    else:
        return

    for key, value in seed.items():
        cur.execute(
            f"INSERT OR IGNORE INTO settings ({key_col}, {value_col}) VALUES (?, ?)",
            (key, str(value)),
        )


def init_phase10_migrations():
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS remediation_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                related_rule_id INTEGER,
                machine_id INTEGER,
                related_alert_id INTEGER,
                status TEXT,
                action_taken TEXT,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        _ensure_column(cur, "remote_commands", "source", "TEXT")
        _ensure_column(cur, "remote_commands", "trigger_alert_id", "INTEGER")
        _ensure_column(cur, "remote_commands", "scheduled_job_id", "INTEGER")

        _seed_settings(cur)

        conn.commit()
    finally:
        conn.close()