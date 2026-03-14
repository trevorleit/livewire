from database import get_db

def create_group(name, description="", color_hex="#60a5fa"):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO machine_groups (group_name, description, color_hex) VALUES (?, ?, ?)",
        (name.strip(), description.strip(), color_hex.strip())
    )
    conn.commit()
    conn.close()

def add_machine_to_group(group_id, machine_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO machine_group_members (group_id, machine_id) VALUES (?, ?)",
        (group_id, machine_id)
    )
    conn.commit()
    conn.close()

def remove_machine_from_group(group_id, machine_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM machine_group_members WHERE group_id=? AND machine_id=?",
        (group_id, machine_id)
    )
    conn.commit()
    conn.close()

def fetch_groups_with_members(cur):
    cur.execute("SELECT * FROM machine_groups ORDER BY group_name ASC")
    groups = cur.fetchall()

    result = []
    for g in groups:
        cur.execute("""
            SELECT m.*
            FROM machine_group_members mgm
            JOIN machines m ON m.id = mgm.machine_id
            WHERE mgm.group_id=?
        """, (g["id"],))
        members = cur.fetchall()

        gd = dict(g)
        gd["members"] = members
        result.append(gd)

    return result