from flask import Blueprint, render_template, request
from database import get_db

inventory_bp = Blueprint("inventory", __name__)

@inventory_bp.route("/inventory", methods=["GET", "POST"])
def inventory():
    conn = get_db()
    cur = conn.cursor()

    if request.method == "POST":
        machine_id = request.form.get("machine_id")
        if machine_id:
            cur.execute("""
                UPDATE machines
                SET display_name = ?, machine_role = ?, location = ?, notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (
                request.form.get("display_name"),
                request.form.get("machine_role"),
                request.form.get("location"),
                request.form.get("notes"),
                machine_id,
            ))
            conn.commit()

    cur.execute("SELECT * FROM machines ORDER BY COALESCE(display_name, hostname) ASC")
    machines = cur.fetchall()
    conn.close()
    return render_template("inventory.html", machines=machines)
