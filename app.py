"""
Mohammad Siddiq Warehouse Management System - Backend API entrypoint.

This file is the main tunnel/linking layer. Shared setup lives in wms_core.py.
Each business area has its own folder with one category file that registers
backend routes and carries the matching frontend reference block.
Replace a category file and restart the backend; app.py links it again here.
"""

import os

from wms_core import app, BASE_DIR, jsonify, send_from_directory

# Category link map. Importing each category file registers its Flask routes.
from auth_users import auth_users
from customers import customers
from inventory import inventory
from stock_io import stock_io
from billing import billing
from dashboard import dashboard
from templates import templates
from export_reports import export_reports
from settings_logs import settings_logs
from file_imports import file_imports


@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_frontend(path):
    """Serve the bundled frontend and fall back to index.html for SPA routes."""
    frontend_dir = BASE_DIR / "ms-warehouse-frontend" / "dist"
    if path and (frontend_dir / path).exists():
        return send_from_directory(frontend_dir, path)
    index_file = frontend_dir / "index.html"
    if index_file.exists():
        return send_from_directory(frontend_dir, "index.html")
    return jsonify({"status": "backend running", "frontend": "dist not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("Mohammad Siddiq Warehouse Management System API")
    print(f"Running on http://localhost:{port}")
    print("Main app.py links category folders:")
    print("  auth_users, customers, inventory, stock_io, billing")
    print("  dashboard, templates, export_reports, settings_logs, file_imports")
    app.run(debug=False, host="0.0.0.0", port=port)
