import os
from flask import Flask

from database import init_db, ensure_rc_schema
from routes.dashboard import dashboard_bp
from routes.machines import machines_bp
from routes.alerts import alerts_bp
from routes.inventory import inventory_bp
from routes.settings import settings_bp
from routes.api import api_bp
from routes.events import events_bp
from routes.actions import actions_bp
from routes.response_center import response_center_bp
from routes.automation import automation_bp
from services.phase10_migrations import init_phase10_migrations
from services.helpers import (
    bytes_to_gb,
    bytes_to_mb,
    mb_to_gb,
    format_last_seen,
    format_uptime,
    format_rate_bps,
    seconds_since,
    is_stale,
    freshness_state,
    freshness_label,
    freshness_badge_class,
)
from services.runtime_settings import get_runtime_settings, fetch_settings
from services.privacy import (
    is_privacy_mode_enabled,
    mask_ip,
    mask_hostname,
    mask_user,
    mask_device_id,
    mask_freeform_text,
    maybe_mask_ip,
    maybe_mask_hostname,
    maybe_mask_user,
    maybe_mask_device_id,
    maybe_mask_freeform_text,
)


def create_app():
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )

    # ---------------------------------------------------------
    # SECRET KEY (required for sessions, flash(), cookies)
    # ---------------------------------------------------------
    app.config["SECRET_KEY"] = os.environ.get(
        "LIVEWIRE_SECRET_KEY",
        "livewire-dev-secret-key"
    )

    # ---------------------------------------------------------
    # Database + migrations
    # ---------------------------------------------------------
    ensure_rc_schema()
    init_db()
    init_phase10_migrations()

    # ---------------------------------------------------------
    # Blueprints
    # ---------------------------------------------------------
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(machines_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(actions_bp)
    app.register_blueprint(response_center_bp)
    app.register_blueprint(automation_bp)

    # ---------------------------------------------------------
    # Template helpers
    # ---------------------------------------------------------
    @app.context_processor
    def inject_helpers():
        runtime_settings = get_runtime_settings()
        settings_map = fetch_settings()

        offline_after_seconds = int(runtime_settings.get("offline_after_seconds", 90) or 90)
        freshness_fresh_seconds = max(30, offline_after_seconds)
        freshness_aging_seconds = max(freshness_fresh_seconds + 30, offline_after_seconds * 2)
        privacy_mode = is_privacy_mode_enabled(settings_map)

        return {
            "bytes_to_gb": bytes_to_gb,
            "bytes_to_mb": bytes_to_mb,
            "mb_to_gb": mb_to_gb,
            "format_uptime": format_uptime,
            "format_last_seen": format_last_seen,
            "format_rate_bps": format_rate_bps,
            "seconds_since": seconds_since,
            "is_stale": is_stale,
            "freshness_state": freshness_state,
            "freshness_label": freshness_label,
            "freshness_badge_class": freshness_badge_class,
            "refresh_seconds": runtime_settings["refresh_seconds"],
            "max_top_processes": runtime_settings["max_top_processes"],
            "offline_after_seconds": offline_after_seconds,
            "freshness_fresh_seconds": freshness_fresh_seconds,
            "freshness_aging_seconds": freshness_aging_seconds,
            "privacy_mode": privacy_mode,
            "mask_ip": mask_ip,
            "mask_host": mask_hostname,
            "mask_user": mask_user,
            "mask_device_id": mask_device_id,
            "mask_freeform_text": mask_freeform_text,
            "maybe_mask_ip": maybe_mask_ip,
            "maybe_mask_hostname": maybe_mask_hostname,
            "maybe_mask_user": maybe_mask_user,
            "maybe_mask_device_id": maybe_mask_device_id,
            "maybe_mask_freeform_text": maybe_mask_freeform_text,
        }

    # ---------------------------------------------------------
    # Debug route
    # ---------------------------------------------------------
    @app.route("/debug-static")
    def debug_static():
        return {
            "static_folder": app.static_folder,
            "template_folder": app.template_folder,
            "static_url_path": app.static_url_path,
        }

    return app


# ---------------------------------------------------------
# Create app
# ---------------------------------------------------------
app = create_app()


# ---------------------------------------------------------
# Run server
# ---------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)