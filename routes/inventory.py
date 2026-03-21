from flask import Blueprint, render_template, request, redirect, url_for, flash

from database import get_db


inventory_bp = Blueprint("inventory", __name__)


def _clean_text(value, fallback=""):
    return str(value or fallback).strip()


@inventory_bp.route("/inventory", methods=["GET", "POST"])
def inventory():
    conn = get_db()
    try:
        cur = conn.cursor()

        if request.method == "POST":
            machine_id = _clean_text(request.form.get("machine_id"))

            if not machine_id or not machine_id.isdigit():
                flash("Invalid machine selection.", "warning")
                return redirect(url_for("inventory.inventory"))

            cur.execute(
                """
                UPDATE machines
                SET display_name = ?,
                    machine_role = ?,
                    location = ?,
                    notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    _clean_text(request.form.get("display_name")),
                    _clean_text(request.form.get("machine_role")),
                    _clean_text(request.form.get("location")),
                    _clean_text(request.form.get("notes")),
                    int(machine_id),
                ),
            )
            conn.commit()
            flash("Machine inventory details saved.", "success")
            return redirect(url_for("inventory.inventory"))

        cur.execute(
            """
            SELECT *
            FROM machines
            ORDER BY COALESCE(display_name, hostname) ASC
            """
        )
        machines = cur.fetchall()

    finally:
        conn.close()

    return render_template("inventory.html", machines=machines)