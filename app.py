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
    format_last_seen,
    format_uptime,
    format_rate_bps,
)
from services.runtime_settings import get_runtime_settings


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
        return {
            "bytes_to_gb": bytes_to_gb,
            "bytes_to_mb": bytes_to_mb,
            "format_uptime": format_uptime,
            "format_last_seen": format_last_seen,
            "format_rate_bps": format_rate_bps,
            "refresh_seconds": runtime_settings["refresh_seconds"],
            "max_top_processes": runtime_settings["max_top_processes"],
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