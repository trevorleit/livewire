from database import get_db


def create_command(
    machine_id,
    action_type,
    payload=None,
    requested_by="local_admin",
    status="pending_approval",
    source="dashboard",
    trigger_alert_id=None,
):
    payload = payload or "{}"
    conn = get_db()
    cur = conn.cursor()
    approved_at_value = "CURRENT_TIMESTAMP" if status == "approved" else "NULL"
    cur.execute(
        f"""
        INSERT INTO remote_commands (
            machine_id, action_type, payload_json, status, requested_by, approved_at, source, trigger_alert_id
        ) VALUES (?, ?, ?, ?, ?, {approved_at_value}, ?, ?)
        """,
        (machine_id, action_type, payload, status, requested_by, source, trigger_alert_id),
    )
    command_id = cur.lastrowid
    conn.commit()
    conn.close()
    return command_id


def approve_command(command_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE remote_commands SET status='approved', approved_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending_approval'",
        (command_id,),
    )
    conn.commit()
    conn.close()


def cancel_command(command_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE remote_commands SET status='cancelled', completed_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('pending_approval','approved','sent')",
        (command_id,),
    )
    conn.commit()
    conn.close()
