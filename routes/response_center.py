
from flask import Blueprint,render_template,request,redirect,url_for
from services.remediation_service import create_rule,get_rules,get_recent_runs,normalize_rule_payload
from services.notification_service import send_test_notification

response_center_bp = Blueprint("response_center",__name__)

@response_center_bp.route("/response-center",methods=["GET","POST"])
def response_center():
    if request.method=="POST":
        form=request.form.get("form_type","")
        if form=="create_rule":
            payload=normalize_rule_payload(
                request.form.get("action_type"),
                request.form.get("service_name",""),
                request.form.get("pid",""),
                request.form.get("delay_seconds","5")
            )
            create_rule(
                request.form.get("rule_name"),
                request.form.get("alert_type"),
                request.form.get("machine_role"),
                request.form.get("action_type"),
                payload,
                request.form.get("cooldown_minutes",30)
            )

        if form=="test_notification":
            send_test_notification()

        return redirect(url_for("response_center.response_center"))

    return render_template(
        "response_center.html",
        rules=get_rules(),
        recent_runs=get_recent_runs()
    )
