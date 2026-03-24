from database import get_db


def create_group(group_name, description="", color_hex="#00cc66"):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO machine_groups (group_name, description, color_hex)
            VALUES (?, ?, ?)
            """,
            (group_name, description, color_hex),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def update_group(group_id, group_name, description="", color_hex="#00cc66"):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE machine_groups
            SET group_name = ?, description = ?, color_hex = ?
            WHERE id = ?
            """,
            (group_name, description, color_hex, group_id),
        )
        conn.commit()
    finally:
        conn.close()


def delete_group(group_id):
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            DELETE FROM machine_group_members
            WHERE group_id = ?
            """,
            (group_id,),
        )

        cur.execute(
            """
            DELETE FROM machine_groups
            WHERE id = ?
            """,
            (group_id,),
        )

        conn.commit()
    finally:
        conn.close()


def add_machine_to_group(group_id, machine_id):
    conn = get_db()
    try:
        cur = conn.cursor()

        cur.execute(
            """
            SELECT 1
            FROM machine_group_members
            WHERE group_id = ? AND machine_id = ?
            """,
            (group_id, machine_id),
        )
        exists = cur.fetchone()

        if not exists:
            cur.execute(
                """
                INSERT INTO machine_group_members (group_id, machine_id)
                VALUES (?, ?)
                """,
                (group_id, machine_id),
            )
            conn.commit()
    finally:
        conn.close()


def remove_machine_from_group(group_id, machine_id):
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            DELETE FROM machine_group_members
            WHERE group_id = ? AND machine_id = ?
            """,
            (group_id, machine_id),
        )
        conn.commit()
    finally:
        conn.close()


def fetch_groups_with_members(cur):
    cur.execute(
        """
        SELECT *
        FROM machine_groups
        ORDER BY group_name COLLATE NOCASE ASC
        """
    )
    groups = [dict(row) for row in cur.fetchall()]

    for group in groups:
        cur.execute(
            """
            SELECT
                m.id,
                m.hostname,
                m.display_name,
                m.machine_role,
                m.is_online
            FROM machine_group_members mgm
            JOIN machines m ON m.id = mgm.machine_id
            WHERE mgm.group_id = ?
            ORDER BY COALESCE(m.display_name, m.hostname) COLLATE NOCASE ASC
            """,
            (group["id"],),
        )
        group["members"] = [dict(row) for row in cur.fetchall()]

    return groups