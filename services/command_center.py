from database import get_db

def create_command(machine_id, action_type, payload=None, requested_by="local_admin"):
    payload = payload or "{}"
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO remote_commands (machine_id, action_type, payload_json, status, requested_by)
        VALUES (?, ?, ?, 'pending_approval', ?)
        """,
        (machine_id, action_type, payload, requested_by),
    )
    conn.commit()
    conn.close()

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
