from flask import Flask
from database import init_db
from routes.dashboard import dashboard_bp
from routes.machines import machines_bp
from routes.alerts import alerts_bp
from routes.inventory import inventory_bp
from routes.settings import settings_bp
from routes.api import api_bp
from routes.events import events_bp
from routes.actions import actions_bp
from services.helpers import bytes_to_gb, bytes_to_mb, format_last_seen, format_uptime, format_rate_bps
from services.runtime_settings import get_runtime_settings

def create_app():
    app = Flask(__name__)
    init_db()

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(machines_bp)
    app.register_blueprint(alerts_bp)
    app.register_blueprint(inventory_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(events_bp)
    app.register_blueprint(actions_bp)

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

    return app

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
