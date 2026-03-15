from flask import Blueprint, render_template, request, redirect, url_for

from database import remediation_rule_from_form, validate_remediation_rule_payload
from services.remediation_service import (
    create_rule,
    get_rules,
    get_recent_runs,
    set_rule_enabled,
)
from services.notification_service import send_test_notification


response_center_bp = Blueprint("response_center", __name__)


@response_center_bp.route("/response-center", methods=["GET", "POST"])
def response_center():
    if request.method == "POST":
        form_type = request.form.get("form_type", "")

        if form_type == "create_rule":
            data = remediation_rule_from_form(request.form)
            errors = validate_remediation_rule_payload(data)

            if not errors:
                create_rule(
                    name=data["name"],
                    alert_type=data["trigger_type"],
                    role=data["machine_role"],
                    action=data["action_type"],
                    payload=json_dumps_safe(data["action_payload"]),
                    cooldown=data["cooldown_seconds"],
                    auto_approve=data["auto_approve"],
                )

        elif form_type == "toggle_rule":
            rule_id = request.form.get("rule_id") or request.form.get("related_rule_id")
            enabled = request.form.get("enabled") == "1"

            if rule_id and str(rule_id).isdigit():
                set_rule_enabled(int(rule_id), enabled)

        elif form_type == "test_notification":
            send_test_notification()

        return redirect(url_for("response_center.response_center"))

    return render_template(
        "response_center.html",
        rules=get_rules(),
        recent_runs=get_recent_runs(),
    )


def json_dumps_safe(value):
    import json

    try:
        return json.dumps(value or {})
    except Exception:
        return "{}"