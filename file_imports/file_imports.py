"""File Imports routes for the WMS backend."""

from wms_core import *

def normalize_header(h):
    if h is None:
        return ""
    h = str(h).split("\n")[0].lower()
    h = re.sub(r"[^a-z0-9 ]", " ", h)
    return re.sub(r"\s+", " ", h).strip()

def map_columns(headers, rules):
    norm = [normalize_header(h) for h in headers]
    used, out = set(), {}
    for field, patterns in rules:
        for idx, nh in enumerate(norm):
            if idx in used or not nh:
                continue
            if any(p in nh for p in patterns):
                out[field] = idx
                used.add(idx)
                break
    return out

def find_header_row(ws, max_scan=15):
    scan = min(ws.max_row, max_scan)
    for r in range(1, scan + 1):
        row_vals = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
        if any(normalize_header(v) == "sku" for v in row_vals):
            return r, row_vals
    for r in range(1, scan + 1):
        row_vals = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
        if any(v is not None and str(v).strip() != "" for v in row_vals):
            return r, row_vals
    return 1, []

def parse_number(val, default=0):
    if val is None or str(val).strip() == "":
        return default
    try:
        n = float(val)
        return int(n) if n.is_integer() else n
    except (TypeError, ValueError):
        return default

def parse_text(row, cols, field):
    if field not in cols or cols[field] >= len(row):
        return None
    val = row[cols[field]]
    if val is None or str(val).strip() == "":
        return None
    return str(val).strip()

def parse_date_cell(val):
    if val is None or str(val).strip() == "":
        return None
    if isinstance(val, datetime.datetime):
        return val.date().isoformat()
    if isinstance(val, datetime.date):
        return val.isoformat()
    s = str(val).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None

def iter_data_rows(ws, header_row):
    for r in range(header_row + 1, ws.max_row + 1):
        row = [ws.cell(row=r, column=c).value for c in range(1, ws.max_column + 1)]
        if any(v is not None and str(v).strip() != "" for v in row):
            yield r, row

INVENTORY_RULES = [
    ("sku", ["sku"]),
    ("customer_name", ["customer"]),
    ("unit_cost", ["unit cost", "cost"]),
    ("min_level", ["min stock", "min level", "minimum"]),
    ("location", ["location"]),
    ("unit", ["unit"]),
    ("qty", ["quantity", "qty"]),
    ("name", ["item name", "name"]),
]

STOCK_IN_RULES = [
    ("sku", ["sku"]),
    ("customer_name", ["customer"]),
    ("unit_cost", ["unit cost"]),
    ("qty", ["quantity received", "quantity", "qty"]),
    ("ref", ["po reference", "po #", "reference", "po"]),
    ("unit", ["unit"]),
    ("name", ["item name", "name"]),
    ("date", ["date"]),
    ("notes", ["notes"]),
]

STOCK_OUT_RULES = [
    ("sku", ["sku"]),
    ("customer_name", ["customer"]),
    ("qty", ["quantity dispatched", "quantity", "qty"]),
    ("ref", ["delivery order", "do #", "reference"]),
    ("unit", ["unit"]),
    ("name", ["item name", "name"]),
    ("date", ["date"]),
    ("notes", ["notes"]),
]

BILLING_RULES = [
    ("num", ["bill no", "bill number", "invoice", "num"]),
    ("date", ["date"]),
    ("customer", ["customer"]),
    ("amount", ["amount", "total"]),
    ("status", ["status"]),
    ("created_by", ["created by", "user"]),
    ("notes", ["notes"]),
]

def import_inventory_excel(path, username):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    header_row, headers = find_header_row(ws)
    cols = map_columns(headers, INVENTORY_RULES)
    if "sku" not in cols:
        return {"added": 0, "updated": 0, "skipped": 0,
                "errors": ["Couldn't find a SKU column — check it matches the inventory template."]}
    inv = load_json(INVENTORY_FILE, [])
    by_sku_customer = {(i.get("sku", ""), i.get("customer_name", "")): i for i in inv}
    added = updated = skipped = 0
    errors = []
    for r, row in iter_data_rows(ws, header_row):
        sku = (parse_text(row, cols, "sku") or "").upper()
        if not sku:
            skipped += 1
            errors.append(f"Row {r}: missing SKU, skipped")
            continue
        name          = parse_text(row, cols, "name")
        customer_name = parse_text(row, cols, "customer_name") or ""
        if not customer_name:
            skipped += 1
            errors.append(f"Row {r}: customer name is mandatory, skipped")
            continue
        unit          = parse_text(row, cols, "unit")
        location      = parse_text(row, cols, "location")
        qty           = parse_number(row[cols["qty"]]) if "qty" in cols else None
        min_level     = parse_number(row[cols["min_level"]]) if "min_level" in cols else None
        unit_cost     = parse_number(row[cols["unit_cost"]]) if "unit_cost" in cols else None
        key = (sku, customer_name)
        if key in by_sku_customer:
            item = by_sku_customer[key]
            if name is not None: item["name"] = name
            if customer_name: item["customer_name"] = customer_name
            if qty is not None: item["qty"] = qty
            if unit is not None: item["unit"] = unit
            if min_level is not None: item["min_level"] = min_level
            if location is not None: item["location"] = location
            if unit_cost is not None: item["unit_cost"] = unit_cost
            item["updated"] = today_str()
            updated += 1
        else:
            item = {
                "id": str(uuid.uuid4()), "sku": sku,
                "name": name or sku, "customer_name": customer_name,
                "customer_id": "", "qty": qty or 0, "unit": unit or "PCS",
                "min_level": min_level or 0, "location": location or "",
                "unit_cost": unit_cost or 0, "updated": today_str(),
                "created_by": username
            }
            inv.append(item)
            by_sku_customer[key] = item
            added += 1
    save_json(INVENTORY_FILE, inv)
    return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}

def import_stock_excel(path, txn_type, username):
    rules = STOCK_IN_RULES if txn_type == "IN" else STOCK_OUT_RULES
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    header_row, headers = find_header_row(ws)
    cols = map_columns(headers, rules)
    if "sku" not in cols or "qty" not in cols:
        return {"processed": 0, "skipped": 0,
                "errors": ["Couldn't find SKU/Quantity columns — check the stock template."]}
    inv = load_json(INVENTORY_FILE, [])
    by_sku_customer = {(i.get("sku", ""), i.get("customer_name", "")): i for i in inv}
    txns = load_json(TRANSACTIONS_FILE, [])
    processed = skipped = 0
    errors = []
    for r, row in iter_data_rows(ws, header_row):
        sku = (parse_text(row, cols, "sku") or "").upper()
        qty = parse_number(row[cols["qty"]], default=0)
        if not sku:
            skipped += 1
            errors.append(f"Row {r}: missing SKU, skipped")
            continue
        if not qty or qty <= 0:
            skipped += 1
            errors.append(f"Row {r} ({sku}): invalid quantity, skipped")
            continue
        name          = parse_text(row, cols, "name")
        customer_name = parse_text(row, cols, "customer_name") or ""
        if not customer_name:
            skipped += 1
            errors.append(f"Row {r}: customer name is mandatory, skipped")
            continue
        unit_cost     = parse_number(row[cols["unit_cost"]]) if "unit_cost" in cols else None
        ref           = parse_text(row, cols, "ref") or "BULK-IMPORT"
        notes         = parse_text(row, cols, "notes") or ""
        date_val      = parse_date_cell(row[cols["date"]]) if "date" in cols else None
        item = by_sku_customer.get((sku, customer_name))
        if not item:
            if txn_type == "OUT":
                skipped += 1
                errors.append(f"Row {r}: SKU {sku} not found in inventory, skipped")
                continue
            item = {
                "id": str(uuid.uuid4()), "sku": sku,
                "name": name or sku, "customer_name": customer_name,
                "customer_id": "", "qty": 0, "unit": "PCS",
                "min_level": 0, "location": "", "unit_cost": unit_cost or 0,
                "updated": today_str(), "created_by": username
            }
            inv.append(item)
            by_sku_customer[(sku, customer_name)] = item
        if txn_type == "OUT":
            if item["qty"] < qty:
                skipped += 1
                errors.append(f"Row {r}: insufficient stock for {sku} (have {item['qty']}, need {qty})")
                continue
            item["qty"] -= qty
        else:
            item["qty"] += qty
            if unit_cost:
                item["unit_cost"] = unit_cost
        item["updated"] = today_str()
        txns.append({
            "id": str(uuid.uuid4()), "datetime": now_str(),
            "date": date_val or today_str(),
            "type": txn_type, "sku": sku, "name": item["name"],
            "customer_name": customer_name or item.get("customer_name", ""),
            "customer_id": "", "qty": qty, "ref": ref,
            "by": username, "status": "Completed", "notes": notes
        })
        processed += 1
    save_json(INVENTORY_FILE, inv)
    save_json(TRANSACTIONS_FILE, txns)
    return {"processed": processed, "skipped": skipped, "errors": errors}

def import_billing_excel(path, username):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    header_row, headers = find_header_row(ws)
    cols = map_columns(headers, BILLING_RULES)
    if "customer" not in cols or "amount" not in cols:
        return {"added": 0, "skipped": 0,
                "errors": ["Couldn't find Customer/Amount columns - check the billing template."]}
    bills = load_json(BILLS_FILE, [])
    added = skipped = 0
    errors = []
    for r, row in iter_data_rows(ws, header_row):
        customer = parse_text(row, cols, "customer") or ""
        amount = parse_number(row[cols["amount"]], default=0) if "amount" in cols else 0
        if not customer:
            skipped += 1
            errors.append(f"Row {r}: customer name is mandatory, skipped")
            continue
        if amount <= 0:
            skipped += 1
            errors.append(f"Row {r}: amount must be greater than zero, skipped")
            continue
        bills.append({
            "id": str(uuid.uuid4()),
            "num": parse_text(row, cols, "num") or f"BILL-{str(len(bills)+1).zfill(4)}",
            "date": parse_date_cell(row[cols["date"]]) if "date" in cols else today_str(),
            "customer": customer,
            "items": 0,
            "amount": amount,
            "status": parse_text(row, cols, "status") or "Pending",
            "notes": parse_text(row, cols, "notes") or "",
            "created_by": parse_text(row, cols, "created_by") or username,
            "created_at": now_str()
        })
        added += 1
    save_json(BILLS_FILE, bills)
    return {"added": added, "skipped": skipped, "errors": errors}

def update_file_status(fid, status, extra=None):
    meta = load_json(FILES_META_FILE, [])
    entry = next((m for m in meta if m["id"] == fid), None)
    if entry:
        entry["status"] = status
        entry["status_updated_at"] = now_str()
        if extra:
            entry.update(extra)
        save_json(FILES_META_FILE, meta)
    return entry

def cleanup_expired_files():
    settings = load_json(SETTINGS_FILE, default_settings())
    try:
        days = int(settings.get("retention_days", 30))
    except (TypeError, ValueError):
        days = 30
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    meta = load_json(FILES_META_FILE, [])
    kept, removed = [], 0
    for entry in meta:
        uploaded_at = entry.get("uploaded_at", "")
        try:
            dt = datetime.datetime.fromisoformat(uploaded_at)
        except ValueError:
            dt = datetime.datetime.now()
        if dt < cutoff:
            path = FILES_DIR / entry.get("filename", "")
            if path.exists():
                path.unlink()
            removed += 1
        else:
            kept.append(entry)
    if removed:
        save_json(FILES_META_FILE, kept)
    return removed

def basic_file_scan(path, ext):
    if ext not in ALLOWED_EXTENSIONS:
        return False, "Unsupported file extension"
    if path.stat().st_size == 0:
        return False, "File is empty"
    if path.stat().st_size > 20 * 1024 * 1024:
        return False, "File exceeds maximum size"
    if ext == ".xlsx":
        try:
            wb = openpyxl.load_workbook(path, read_only=True)
            wb.close()
        except Exception as e:
            return False, f"File failed integrity check: {e}"
    return True, "OK"

def file_log_event(username, action, entry, status="done", notes=""):
    log_activity(username, action, "File Log",
                 f"{entry.get('original_name') or entry.get('filename')} ({entry.get('type', 'file')})",
                 "error" if status == "error" else "success",
                 meta={
                     "file_id": entry.get("id"),
                     "file_name": entry.get("original_name") or entry.get("filename"),
                     "file_type": entry.get("type", ""),
                     "file_status": status,
                     "notes": notes or entry.get("notes") or entry.get("error") or "",
                     "direction": "download" if "download" in action.lower() else "upload"
                 })

@app.route("/api/files/upload", methods=["POST"])
@require_auth
def upload_file():
    cleanup_expired_files()
    username = request.current_user["username"]
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    ext = Path(f.filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": "Only .xlsx and .xls files allowed"}), 400
    file_type = request.form.get("type", "inventory")
    date_str  = request.form.get("date", today_str())
    date_folder = re.sub(r"[^0-9-]", "", date_str) or today_str()
    dated_dir = FILES_DIR / date_folder
    dated_dir.mkdir(parents=True, exist_ok=True)
    safe_name = f"{file_type}_{date_folder}_{uuid.uuid4().hex[:8]}{ext}"
    stored_name = f"{date_folder}/{safe_name}"
    save_path = dated_dir / safe_name
    fid = str(uuid.uuid4())
    meta = load_json(FILES_META_FILE, [])
    entry = {
        "id": fid, "filename": stored_name,
        "original_name": f.filename, "type": file_type,
        "date": date_str, "size_kb": 0,
        "uploaded_by": username, "uploaded_at": now_str(),
        "status": "uploading", "status_updated_at": now_str(),
    }
    meta.append(entry)
    save_json(FILES_META_FILE, meta)
    try:
        f.save(save_path)
    except Exception as e:
        update_file_status(fid, "error", {"error": str(e)})
        return jsonify({"error": str(e)}), 500
    size_kb = round(save_path.stat().st_size / 1024, 1)
    update_file_status(fid, "reading", {"size_kb": size_kb, "notes": "Reading uploaded file"})
    ok, reason = basic_file_scan(save_path, ext)
    if not ok:
        update_file_status(fid, "error", {"error": reason, "notes": reason})
        return jsonify({"id": fid, "status": "error", "error": reason}), 400
    update_file_status(fid, "getting data", {"notes": "Getting data from workbook"})
    import_result = None
    if ext == ".xlsx":
        try:
            if file_type == "inventory":
                import_result = import_inventory_excel(save_path, username)
            elif file_type == "stock_in":
                import_result = import_stock_excel(save_path, "IN", username)
            elif file_type == "stock_out":
                import_result = import_stock_excel(save_path, "OUT", username)
            elif file_type == "billing":
                import_result = import_billing_excel(save_path, username)
        except Exception as e:
            import_result = {"error": str(e)}
    if import_result and import_result.get("error"):
        update_file_status(fid, "error", {"error": import_result["error"], "notes": import_result["error"]})
    else:
        notes = ""
        if import_result and import_result.get("errors"):
            notes = "; ".join(import_result["errors"][:8])
        update_file_status(fid, "done", {"import_result": import_result, "notes": notes})
    log_activity(username, "File uploaded and processed", "Files",
                 f"{f.filename} ({file_type})", meta={"file_id": fid})
    meta2 = load_json(FILES_META_FILE, [])
    final = next((m for m in meta2 if m["id"] == fid), entry)
    final_status = "error" if import_result and import_result.get("error") else "done"
    file_log_event(username, "Uploaded file", final, final_status, final.get("notes", ""))
    return jsonify({**final, "import_result": import_result}), 201

@app.route("/api/files", methods=["GET"])
@require_auth
def list_files():
    cleanup_expired_files()
    meta = load_json(FILES_META_FILE, [])
    t = request.args.get("type", "")
    if t:
        meta = [m for m in meta if m["type"] == t]
    return jsonify(meta[::-1])

@app.route("/api/files/<fid>", methods=["DELETE"])
@require_auth
def delete_file(fid):
    meta = load_json(FILES_META_FILE, [])
    entry = next((m for m in meta if m["id"] == fid), None)
    if not entry:
        return jsonify({"error": "File not found"}), 404
    path = FILES_DIR / entry["filename"]
    if path.exists():
        path.unlink()
    meta = [m for m in meta if m["id"] != fid]
    save_json(FILES_META_FILE, meta)
    log_activity(request.current_user["username"], "Deleted file", "Files",
                 entry.get("original_name", entry["filename"]))
    return jsonify({"message": "File deleted"})

@app.route("/api/files/<fid>/download", methods=["GET"])
@require_auth
def download_file(fid):
    meta = load_json(FILES_META_FILE, [])
    entry = next((m for m in meta if m["id"] == fid), None)
    if not entry:
        return jsonify({"error": "File not found"}), 404
    path = FILES_DIR / entry["filename"]
    if not path.exists():
        return jsonify({"error": "File missing from disk"}), 404
    file_log_event(request.current_user["username"], "Downloaded file", entry, "done", "File downloaded by user")
    return send_file(path, as_attachment=True, download_name=entry["original_name"])


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
async function renderTemplates() {
  setMain(`
    <div class="page-header">
      <div><h1>Templates</h1><div class="subtitle">Manage Excel template column headings</div></div>
    </div>
    <div class="page-body" id="tmpl-body">${loadingHtml()}</div>`);
  try {
    const data = await API('/templates');
    const headers = data.all_headers || {};
    let html = `<div class="card"><div class="card-header"><h3>Template Column Headings</h3><button class="btn btn-accent btn-sm" onclick="saveTemplateHeaders()">Save Changes</button></div><div class="card-body">`;
    for (const [key, cols] of Object.entries(headers)) {
      html += `<div style="margin-bottom:24px"><h4 style="font-size:13px;font-weight:700;text-transform:capitalize;margin-bottom:12px;padding-bottom:8px;border-bottom:1px solid var(--surface-3)">${key.replace(/_/g,' ')}</h4>
        <div class="field-row-3">`;
      for (const [col, label] of Object.entries(cols)) {
        html += `<div class="field"><label style="font-size:11px;color:var(--ink-4)">${col}</label>
          <input data-tkey="${key}" data-col="${col}" value="${label}"/></div>`;
      }
      html += `</div></div>`;
    }
    html += `</div></div>`;

    // Template downloads
    html += `<div class="card" style="margin-top:16px"><div class="card-header"><h3>Download Templates</h3></div><div class="card-body">
      <div style="display:flex;gap:10px;flex-wrap:wrap">`;
    for (const key of Object.keys(headers)) {
      html += `<a href="/api/templates/generate/${key}" class="btn btn-ghost btn-sm" target="_blank">${icon.export} ${key.replace(/_/g,' ')}</a>`;
    }
    html += `</div></div></div>`;

    document.getElementById('tmpl-body').innerHTML = html;
  } catch(e) { document.getElementById('tmpl-body').innerHTML=`<p class="text-danger">${e.message}</p>`; }
}

async function saveTemplateHeaders() {
  const inputs = document.querySelectorAll('[data-tkey][data-col]');
  const update = {};
  inputs.forEach(inp => {
    const k = inp.dataset.tkey, c = inp.dataset.col;
    if (!update[k]) update[k] = {};
    update[k][c] = inp.value;
  });
  try {
    await API('/templates/headers', {method:'PUT', body:JSON.stringify(update)});
    toast('Template headers saved','success');
  } catch(e) { toast(e.message,'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   REPORTS
═══════════════════════════════════════════════════════════════════════════ */
"""
