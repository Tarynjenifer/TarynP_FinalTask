"""
main.py
-------
Flask application entry point. Wires together the database, the API
blueprints, and the static frontend. Global error handlers return
clean JSON for all API failures.
"""

import json
import logging
from pathlib import Path

from flask import Flask, render_template, jsonify
from werkzeug.exceptions import HTTPException

from app.database import init_db
from app.routes.tickets import bp as tickets_bp
from app.routes.support import bp as support_bp
from app.routes.dashboard import bp as dashboard_bp

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ticket_system")

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"

app = Flask(
    __name__,
    static_folder=str(STATIC_DIR),
    template_folder=str(TEMPLATES_DIR),
)

with app.app_context():
    init_db()
    logger.info("Database initialized at startup.")


@app.errorhandler(HTTPException)
def handle_http_exception(error):
    response = jsonify({"detail": error.description})
    return response, error.code


@app.errorhandler(Exception)
def handle_unhandled_exception(error):
    logger.exception("Unhandled server error")
    return jsonify({"detail": "Internal server error"}), 500


app.register_blueprint(tickets_bp)
app.register_blueprint(support_bp)
app.register_blueprint(dashboard_bp)


@app.route("/")
def serve_customer_page():
    return render_template("index.html")


@app.route("/support")
def serve_support_page():
    return render_template("support.html")


@app.route("/admin")
def serve_admin_page():
    return render_template("admin.html")


@app.route("/api/health")
def health_check():
    return jsonify({"status": "ok"})
