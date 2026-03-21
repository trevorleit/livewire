import json
import sqlite3

HOSTNAME = "DESKTOP-79L3KQS"

conn = sqlite3.connect(r"instance\dashboard.db")
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """
    SELECT id, machine_id, recorded_at, gpu_name, gpu_json
    FROM snapshots
    WHERE machine_id = (
        SELECT id FROM machines WHERE hostname = ?
    )
    ORDER BY id DESC
    LIMIT 3
    """,
    (HOSTNAME,),
).fetchall()

print(json.dumps([dict(r) for r in rows], indent=2))
conn.close()