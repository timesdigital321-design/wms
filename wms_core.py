"""
Mohammad Siddiq Warehouse Management System — Backend API
Flask REST API with file storage, user management, and inventory tracking.

New features (v2):
  - Inventory & Stock In/Out maintained per-customer (not by item category)
  - Bulk operations: bulk edit inventory, bulk stock-in/out
  - Customer onboarding: every user can onboard/manage customers
  - Admin sees all customers + which user owns them (name row + username row)
  - Users see only their own customers
  - Dashboard summary scoped to logged-in user's own transactions
  - Admin dashboard = own transactions + per-user breakdown
  - Role-based access: users get only the modules admin grants
  - Templates section (admin only) with editable column headings
  - Export reports: day/week/custom; admin: user-wise + all-users summary
"""

import os, json, hashlib, datetime, shutil, uuid, re, io
from pathlib import Path
from functools import wraps
from flask import Flask, request, jsonify, send_file, send_from_directory
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# ── Config ────────────────────────────────────────────────────────────────────
BASE_DIR  = Path(__file__).parent
DATA_DIR  = BASE_DIR / "data"
FILES_DIR = BASE_DIR / "uploaded_files"
TEMPL_DIR = BASE_DIR / "excel_templates"
BACKUP_DIR = BASE_DIR / "backups"
ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

DATA_DIR.mkdir(exist_ok=True)
FILES_DIR.mkdir(exist_ok=True)
TEMPL_DIR.mkdir(exist_ok=True)
BACKUP_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB

# ── Helpers ───────────────────────────────────────────────────────────────────
def load_json(path, default):
    if Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return default

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)

def hash_pw(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def now_str():
    return datetime.datetime.now().isoformat(timespec="seconds")

def today_str():
    return datetime.date.today().isoformat()

def parse_iso_datetime(value):
    try:
        return datetime.datetime.fromisoformat(value or "")
    except (TypeError, ValueError):
        return None

# ── Data Stores ───────────────────────────────────────────────────────────────
USERS_FILE        = DATA_DIR / "users.json"
INVENTORY_FILE    = DATA_DIR / "inventory.json"
TRANSACTIONS_FILE = DATA_DIR / "transactions.json"
BILLS_FILE        = DATA_DIR / "bills.json"
SETTINGS_FILE     = DATA_DIR / "settings.json"
FILES_META_FILE   = DATA_DIR / "files_meta.json"
SESSIONS_FILE     = DATA_DIR / "sessions.json"
LOGS_FILE         = DATA_DIR / "activity_logs.json"
CUSTOMERS_FILE    = DATA_DIR / "customers.json"
TEMPL_HEADERS_FILE= DATA_DIR / "template_headers.json"

MODULES = [
    "Dashboard", "Inventory", "Stock In/Out", "Billing",
    "Reports", "Activity Log", "Customers", "Templates", "Export"
]

MAX_LOG_ENTRIES = 5000
SESSION_TIMEOUT_SECONDS = 3 * 60 * 60

# ── Activity Log ──────────────────────────────────────────────────────────────
def log_activity(username, action, category, details="", status="success", meta=None):
    try:
        logs = load_json(LOGS_FILE, [])
        entry = {
            "id": str(uuid.uuid4()),
            "datetime": now_str(),
            "username": username or "system",
            "action": action,
            "category": category,
            "details": details,
            "status": status,
        }
        if meta:
            entry["meta"] = meta
        logs.append(entry)
        if len(logs) > MAX_LOG_ENTRIES:
            logs = logs[-MAX_LOG_ENTRIES:]
        save_json(LOGS_FILE, logs)
        return entry
    except Exception:
        return None

# ── CORS ──────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    return response

@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return jsonify({}), 200

# ── Default Data ──────────────────────────────────────────────────────────────
def default_users():
    return [
        {
            "id": "u1", "name": "Mohammad Siddiq", "username": "admin",
            "password": hash_pw("admin123"), "role": "Admin",
            "access": MODULES, "status": "Active",
            "created": today_str(), "last_login": None
        },
        {
            "id": "u2", "name": "Ahmed Al-Rashid", "username": "staff",
            "password": hash_pw("staff123"), "role": "Staff",
            "access": ["Dashboard", "Inventory", "Stock In/Out", "Customers", "Activity Log"],
            "status": "Active", "created": today_str(), "last_login": None
        }
    ]

def default_inventory():
    # Inventory is now customer-centric: each item record links to a customer
    return [
        {"id": str(uuid.uuid4()), "sku": "ELC-001", "name": "Motor Controller Unit",
         "customer_id": "", "customer_name": "Al-Noor Supplies",
         "qty": 245, "unit": "PCS", "min_level": 50,
         "unit_cost": 180.0, "location": "A-01-1", "updated": today_str(), "created_by": "admin"},
        {"id": str(uuid.uuid4()), "sku": "ELC-002", "name": "Relay Switch 24V",
         "customer_id": "", "customer_name": "Gulf Industries",
         "qty": 18, "unit": "PCS", "min_level": 30,
         "unit_cost": 45.0, "location": "A-01-2", "updated": today_str(), "created_by": "admin"},
        {"id": str(uuid.uuid4()), "sku": "SPA-001", "name": "Bearing SKF 6205",
         "customer_id": "", "customer_name": "Industrial Corp KSA",
         "qty": 320, "unit": "PCS", "min_level": 100,
         "unit_cost": 28.0, "location": "B-02-1", "updated": today_str(), "created_by": "admin"},
        {"id": str(uuid.uuid4()), "sku": "PKG-001", "name": "Cardboard Box L",
         "customer_id": "", "customer_name": "Riyadh Packaging Co",
         "qty": 2400, "unit": "PCS", "min_level": 1000,
         "unit_cost": 2.1, "location": "E-01-1", "updated": today_str(), "created_by": "admin"},
    ]

def default_transactions():
    return [
        {"id": "t1", "datetime": now_str(), "date": today_str(), "type": "IN",
         "sku": "ELC-001", "name": "Motor Controller Unit",
         "customer_id": "", "customer_name": "Al-Noor Supplies",
         "qty": 50, "ref": "PO-2024-128", "by": "admin", "status": "Completed", "notes": ""},
        {"id": "t2", "datetime": now_str(), "date": today_str(), "type": "OUT",
         "sku": "ELC-001", "name": "Motor Controller Unit",
         "customer_id": "", "customer_name": "Gulf Industries",
         "qty": 10, "ref": "DO-2024-214", "by": "staff", "status": "Completed", "notes": ""},
    ]

def default_bills():
    return [
        {"id": "b1", "num": "BILL-0284", "date": today_str(), "customer": "Gulf Industries LLC",
         "items": 3, "amount": 18400, "status": "Pending", "notes": "", "created_by": "admin", "created_at": now_str()},
        {"id": "b2", "num": "BILL-0283", "date": today_str(), "customer": "Industrial Corp KSA",
         "items": 5, "amount": 42800, "status": "Paid",    "notes": "", "created_by": "admin", "created_at": now_str()},
    ]

def default_customers():
    return [
        {"id": "c1", "name": "Al-Noor Supplies",    "phone": "", "email": "", "address": "",
         "assigned_to": "admin",  "created_by": "admin", "created_at": now_str(), "status": "Active", "notes": ""},
        {"id": "c2", "name": "Gulf Industries",      "phone": "", "email": "", "address": "",
         "assigned_to": "staff",  "created_by": "admin", "created_at": now_str(), "status": "Active", "notes": ""},
        {"id": "c3", "name": "Industrial Corp KSA",  "phone": "", "email": "", "address": "",
         "assigned_to": "admin",  "created_by": "admin", "created_at": now_str(), "status": "Active", "notes": ""},
        {"id": "c4", "name": "Riyadh Packaging Co",  "phone": "", "email": "", "address": "",
         "assigned_to": "staff",  "created_by": "staff", "created_at": now_str(), "status": "Active", "notes": ""},
    ]

def default_settings():
    return {
        "warehouse_name": "Mohammad Siddiq Warehouse",
        "location": "Riyadh, Saudi Arabia",
        "manager": "Mohammad Siddiq",
        "phone": "+966 5X XXX XXXX",
        "currency": "SAR",
        "date_format": "DD/MM/YYYY",
        "retention_days": 30,
        "vat_percent": 15
    }

def default_template_headers():
    """Admin-editable column headings for each Excel template."""
    return {
        "inventory": {
            "sku": "SKU", "name": "Item Name", "customer_name": "Customer",
            "qty": "Quantity", "unit": "Unit", "unit_cost": "Unit Cost",
            "min_level": "Min Stock", "location": "Location"
        },
        "stock_in": {
            "sku": "SKU", "name": "Item Name", "customer_name": "Customer",
            "qty": "Quantity Received", "unit": "Unit", "unit_cost": "Unit Cost",
            "ref": "PO Reference", "date": "Date", "notes": "Notes"
        },
        "stock_out": {
            "sku": "SKU", "name": "Item Name", "customer_name": "Customer",
            "qty": "Quantity Dispatched", "unit": "Unit",
            "ref": "Delivery Order", "date": "Date", "notes": "Notes"
        },
        "daily_report": {
            "date": "Date", "customer_name": "Customer", "sku": "SKU",
            "name": "Item Name", "type": "IN/OUT", "qty": "Quantity",
            "ref": "Reference", "by": "Handled By"
        },
        "billing": {
            "bill_num": "Bill No", "date": "Date", "customer": "Customer",
            "amount": "Amount (SAR)", "status": "Status", "created_by": "Created By"
        }
    }

# Initialise data files if absent
for f, default in [
    (USERS_FILE, default_users()), (INVENTORY_FILE, default_inventory()),
    (TRANSACTIONS_FILE, default_transactions()), (BILLS_FILE, default_bills()),
    (SETTINGS_FILE, default_settings()), (FILES_META_FILE, []), (SESSIONS_FILE, {}),
    (LOGS_FILE, []), (CUSTOMERS_FILE, default_customers()),
    (TEMPL_HEADERS_FILE, default_template_headers())
]:
    if not f.exists():
        save_json(f, default)

# ── Auth ──────────────────────────────────────────────────────────────────────
def require_auth(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        token = request.headers.get("Authorization", "").replace("Bearer ", "")
        sessions = load_json(SESSIONS_FILE, {})
        if token not in sessions:
            return jsonify({"error": "Unauthorized"}), 401
        sess = sessions[token]
        now = datetime.datetime.now()
        expires_at = parse_iso_datetime(sess.get("expires_at"))
        if expires_at and now >= expires_at:
            sessions.pop(token, None)
            save_json(SESSIONS_FILE, sessions)
            return jsonify({"error": "Session expired"}), 401
        if not expires_at:
            sess["expires_at"] = (now + datetime.timedelta(seconds=SESSION_TIMEOUT_SECONDS)).isoformat(timespec="seconds")
            sessions[token] = sess
            save_json(SESSIONS_FILE, sessions)
        request.current_user = sessions[token]
        return fn(*args, **kwargs)
    return wrapped

def require_admin(fn):
    @wraps(fn)
    @require_auth
    def wrapped(*args, **kwargs):
        if request.current_user.get("role") != "Admin":
            return jsonify({"error": "Admin access required"}), 403
        return fn(*args, **kwargs)
    return wrapped

def has_access(user, module):
    """Check if user has access to a given module."""
    return user.get("role") == "Admin" or module in user.get("access", [])

def require_module(module):
    """Decorator to check module access."""
    def decorator(fn):
        @wraps(fn)
        @require_auth
        def wrapped(*args, **kwargs):
            if not has_access(request.current_user, module):
                return jsonify({"error": f"Access to '{module}' not granted"}), 403
            return fn(*args, **kwargs)
        return wrapped
    return decorator

# ── Customer-scoping helpers (hardening) ────────────────────────────────────────
# Inventory and Stock In/Out are customer-centric. Non-admins must only be able
# to create/edit/move stock for customers assigned to them; admins are unrestricted.
def get_user_customers(cu, customers=None):
    """Customers assigned to this user. Admins get the full list."""
    if customers is None:
        customers = load_json(CUSTOMERS_FILE, [])
    if cu["role"] == "Admin":
        return customers
    return [c for c in customers if c.get("assigned_to") == cu["username"]]

def resolve_customer_for_user(cu, customer_id="", customer_name="", customers=None):
    """
    Validates a requested customer_id/customer_name against the user's own
    customers. Admins can assign any customer (or leave it blank) freely.
    Returns (resolved_id, resolved_name, error) — error is a (response, status)
    tuple to return immediately on failure, or None on success.
    """
    if cu["role"] == "Admin":
        return customer_id, customer_name, None
    my_customers = get_user_customers(cu, customers)
    match = None
    if customer_id:
        match = next((c for c in my_customers if c["id"] == customer_id), None)
    elif customer_name:
        match = next((c for c in my_customers if c["name"] == customer_name), None)
    if not match:
        return None, None, (jsonify({"error": "You can only use your own customers"}), 403)
    return match["id"], match["name"], None

def user_owns_inventory_item(cu, item, customers=None):
    """Whether a non-admin may act on this inventory item (own item or own customer's item)."""
    if cu["role"] == "Admin":
        return True
    if item.get("created_by") == cu["username"]:
        return True
    my_names = {c["name"] for c in get_user_customers(cu, customers)}
    return item.get("customer_name", "") in my_names

# ── Login / Auth ──────────────────────────────────────────────────────────────
