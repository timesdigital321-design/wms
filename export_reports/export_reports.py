"""Export Reports routes for the WMS backend."""

from wms_core import *

def _date_range(range_type, date_from=None, date_to=None):
    today = datetime.date.today()
    if range_type == "day":
        return today.isoformat(), today.isoformat()
    elif range_type == "week":
        start = today - datetime.timedelta(days=today.weekday())
        return start.isoformat(), today.isoformat()
    elif range_type == "custom":
        return date_from or today.isoformat(), date_to or today.isoformat()
    return date_from or "2000-01-01", date_to or today.isoformat()

def _filter_txns(txns, date_from, date_to, username=None):
    result = []
    for t in txns:
        d = t.get("date") or t["datetime"][:10]
        if date_from <= d <= date_to:
            if username is None or t.get("by") == username:
                result.append(t)
    return result

def _filter_bills(bills, date_from, date_to, username=None):
    result = []
    for b in bills:
        d = b.get("date") or b.get("created_at", "")[:10]
        if date_from <= d <= date_to:
            if username is None or b.get("created_by") == username:
                result.append(b)
    return result

def _build_excel_report(title, txns, bills, inv_snapshot=None, username_label=None):
    """Build a multi-sheet Excel report workbook."""
    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    hfont = Font(color="FFFFFF", bold=True)

    def style_header(ws, headers, row=1):
        for col, h in enumerate(headers, 1):
            c = ws.cell(row=row, column=col, value=h)
            c.fill = header_fill
            c.font = hfont
            ws.column_dimensions[get_column_letter(col)].width = max(len(str(h)) + 4, 14)

    # Sheet 1: Transactions
    ws1 = wb.active
    ws1.title = "Stock Movements"
    ws1["A1"] = f"{title}{' — ' + username_label if username_label else ''}"
    ws1.merge_cells("A1:I1")
    ws1["A1"].font = Font(bold=True, size=13)
    ws1["A2"] = f"Generated: {now_str()}"
    style_header(ws1, ["Date", "Type", "SKU", "Item Name", "Customer", "Qty", "Ref", "By", "Notes"], row=3)
    for row_idx, t in enumerate(txns, start=3):
        ws1.append([
            t.get("date") or t["datetime"][:10], t["type"], t.get("sku", ""),
            t.get("name", ""), t.get("customer_name", ""), t.get("qty", 0),
            t.get("ref", ""), t.get("by", ""), t.get("notes", "")
        ])
    # Totals row
    ws1.append(["", "", "", "", "TOTAL IN:",
                 sum(t["qty"] for t in txns if t["type"] == "IN"), "", "", ""])
    ws1.append(["", "", "", "", "TOTAL OUT:",
                 sum(t["qty"] for t in txns if t["type"] == "OUT"), "", "", ""])

    # Sheet 2: Bills
    ws2 = wb.create_sheet("Billing")
    style_header(ws2, ["Date", "Bill No", "Customer", "Amount (SAR)", "Status", "Created By"])
    for b in bills:
        ws2.append([b.get("date", ""), b.get("num", ""), b.get("customer", ""),
                    b.get("amount", 0), b.get("status", ""), b.get("created_by", "")])
    ws2.append(["", "", "TOTAL PAID",
                 sum(b["amount"] for b in bills if b["status"] == "Paid"), "", ""])
    ws2.append(["", "", "TOTAL PENDING",
                 sum(b["amount"] for b in bills if b["status"] == "Pending"), "", ""])

    # Sheet 3: Inventory snapshot (if provided)
    if inv_snapshot is not None:
        ws3 = wb.create_sheet("Inventory Snapshot")
        style_header(ws3, ["SKU", "Item Name", "Customer", "Qty", "Unit",
                            "Min Level", "Unit Cost (SAR)", "Value (SAR)", "Location"])
        for i in inv_snapshot:
            value = i.get("qty", 0) * i.get("unit_cost", 0)
            ws3.append([i.get("sku", ""), i["name"], i.get("customer_name", ""),
                        i.get("qty", 0), i.get("unit", ""), i.get("min_level", 0),
                        i.get("unit_cost", 0), round(value, 2), i.get("location", "")])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf

@app.route("/api/export/report", methods=["GET"])
@require_auth
def export_report():
    """
    Export report for the logged-in user.
    Params: range=day|week|custom, date_from, date_to, include_inventory=0|1
    """
    cu = request.current_user
    is_admin = cu["role"] == "Admin"
    range_type = request.args.get("range", "day")
    date_from, date_to = _date_range(
        range_type,
        request.args.get("date_from"),
        request.args.get("date_to")
    )
    include_inv = request.args.get("include_inventory", "0") == "1"
    all_txns  = load_json(TRANSACTIONS_FILE, [])
    all_bills = load_json(BILLS_FILE, [])
    all_inv   = load_json(INVENTORY_FILE, [])

    if is_admin:
        txns  = _filter_txns(all_txns, date_from, date_to)
        bills = _filter_bills(all_bills, date_from, date_to)
        inv   = all_inv if include_inv else None
    else:
        txns  = _filter_txns(all_txns, date_from, date_to, cu["username"])
        bills = _filter_bills(all_bills, date_from, date_to, cu["username"])
        my_cust = {c["name"] for c in load_json(CUSTOMERS_FILE, [])
                   if c.get("assigned_to") == cu["username"]}
        inv = [i for i in all_inv if i.get("customer_name") in my_cust
               or i.get("created_by") == cu["username"]] if include_inv else None

    title = f"WMS Report ({date_from} to {date_to})"
    buf = _build_excel_report(title, txns, bills, inv)
    filename = f"report_{cu['username']}_{date_from}_{date_to}.xlsx"
    log_activity(cu["username"], "Exported report", "Export",
                 f"range:{range_type} {date_from}~{date_to}")
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/export/report/user/<target_username>", methods=["GET"])
@require_admin
def export_report_by_user(target_username):
    """Admin: export report filtered to a specific user."""
    range_type = request.args.get("range", "week")
    date_from, date_to = _date_range(
        range_type,
        request.args.get("date_from"),
        request.args.get("date_to")
    )
    include_inv = request.args.get("include_inventory", "0") == "1"
    all_txns  = load_json(TRANSACTIONS_FILE, [])
    all_bills = load_json(BILLS_FILE, [])
    all_inv   = load_json(INVENTORY_FILE, [])
    txns  = _filter_txns(all_txns, date_from, date_to, target_username)
    bills = _filter_bills(all_bills, date_from, date_to, target_username)
    inv   = [i for i in all_inv if i.get("created_by") == target_username] if include_inv else None
    title = f"WMS User Report — {target_username} ({date_from} to {date_to})"
    buf = _build_excel_report(title, txns, bills, inv, username_label=target_username)
    filename = f"report_{target_username}_{date_from}_{date_to}.xlsx"
    log_activity(request.current_user["username"], "Exported user report", "Export",
                 f"user:{target_username} {date_from}~{date_to}")
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/export/report/all-users-summary", methods=["GET"])
@require_admin
def export_all_users_summary():
    """Admin: export a summary across all users in a single workbook — one sheet per user."""
    range_type = request.args.get("range", "week")
    date_from, date_to = _date_range(
        range_type,
        request.args.get("date_from"),
        request.args.get("date_to")
    )
    all_txns  = load_json(TRANSACTIONS_FILE, [])
    all_bills = load_json(BILLS_FILE, [])
    all_inv   = load_json(INVENTORY_FILE, [])
    users     = load_json(USERS_FILE, [])
    customers = load_json(CUSTOMERS_FILE, [])
    wb = openpyxl.Workbook()
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    hfont = Font(color="FFFFFF", bold=True)

    def style_header(ws, cols, row=1):
        for col, h in enumerate(cols, 1):
            c = ws.cell(row=row, column=col, value=h)
            c.fill = header_fill
            c.font = hfont
            ws.column_dimensions[get_column_letter(col)].width = max(len(str(h)) + 4, 14)

    # Summary sheet
    ws_sum = wb.active
    ws_sum.title = "All Users Summary"
    ws_sum["A1"] = f"All Users Summary — {date_from} to {date_to}"
    ws_sum["A1"].font = Font(bold=True, size=13)
    ws_sum.merge_cells("A1:G1")
    style_header(ws_sum, ["Username", "Full Name", "Customers", "Txns (IN)", "Txns (OUT)",
                            "Bills Created", "Bill Value (SAR)"], row=2)
    for u in users:
        uname = u["username"]
        u_txns  = _filter_txns(all_txns, date_from, date_to, uname)
        u_bills = _filter_bills(all_bills, date_from, date_to, uname)
        u_cust  = [c for c in customers if c.get("assigned_to") == uname]
        ws_sum.append([
            uname, u["name"], len(u_cust),
            sum(t["qty"] for t in u_txns if t["type"] == "IN"),
            sum(t["qty"] for t in u_txns if t["type"] == "OUT"),
            len(u_bills),
            round(sum(b["amount"] for b in u_bills), 2)
        ])

    # Per-user detail sheets
    for u in users:
        uname = u["username"]
        safe_name = uname[:28]  # Excel sheet name limit
        ws = wb.create_sheet(title=safe_name)
        u_txns  = _filter_txns(all_txns, date_from, date_to, uname)
        u_bills = _filter_bills(all_bills, date_from, date_to, uname)
        ws["A1"] = f"{u['name']} ({uname}) — {date_from} to {date_to}"
        ws["A1"].font = Font(bold=True, size=12)
        ws.merge_cells("A1:I1")
        style_header(ws, ["Date", "Type", "SKU", "Item", "Customer", "Qty", "Ref",
                           "Bill No", "Bill Amount"], row=2)
        for t in u_txns:
            ws.append([t.get("date") or t["datetime"][:10], t["type"], t.get("sku", ""),
                        t.get("name", ""), t.get("customer_name", ""), t.get("qty", 0),
                        t.get("ref", ""), "", ""])
        for b in u_bills:
            ws.append([b.get("date", ""), "BILL", "", "", b.get("customer", ""), "",
                        "", b.get("num", ""), b.get("amount", 0)])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"all_users_summary_{date_from}_{date_to}.xlsx"
    log_activity(request.current_user["username"], "Exported all-users summary", "Export",
                 f"{date_from}~{date_to}")
    return send_file(buf, as_attachment=True, download_name=filename,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/export/inventory", methods=["GET"])
@require_auth
def export_inventory_excel():
    """Export the current inventory snapshot to Excel."""
    cu = request.current_user
    inv = load_json(INVENTORY_FILE, [])
    if cu["role"] != "Admin":
        my_cust = {c["name"] for c in load_json(CUSTOMERS_FILE, [])
                   if c.get("assigned_to") == cu["username"]}
        inv = [i for i in inv if i.get("customer_name") in my_cust
               or i.get("created_by") == cu["username"]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Inventory"
    headers = ["SKU", "Item Name", "Customer", "Quantity", "Unit", "Unit Cost",
               "Min Stock", "Location", "Updated", "Created By"]
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    hfont = Font(color="FFFFFF", bold=True)
    for col, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=col, value=h)
        c.fill = header_fill
        c.font = hfont
        ws.column_dimensions[get_column_letter(col)].width = max(len(h) + 4, 14)
    for i in inv:
        ws.append([
            i.get("sku", ""), i.get("name", ""), i.get("customer_name", ""),
            i.get("qty", 0), i.get("unit", ""), i.get("unit_cost", 0),
            i.get("min_level", 0), i.get("location", ""), i.get("updated", ""),
            i.get("created_by", "")
        ])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    log_activity(cu["username"], "Exported inventory", "Export", f"{len(inv)} rows")
    return send_file(buf, as_attachment=True, download_name=f"inventory_export_{today_str()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

@app.route("/api/admin/backup", methods=["GET"])
@require_admin
def admin_backup():
    """
    Create a zip backup grouped by user, then category:
    users/<username>/{inventory,transactions,billing,customers,uploads}
    plus admin/global settings/templates/logs.
    """
    users = load_json(USERS_FILE, [])
    inv = load_json(INVENTORY_FILE, [])
    txns = load_json(TRANSACTIONS_FILE, [])
    bills = load_json(BILLS_FILE, [])
    customers = load_json(CUSTOMERS_FILE, [])
    files_meta = load_json(FILES_META_FILE, [])
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = BACKUP_DIR / f"backup_{stamp}"
    if backup_root.exists():
        shutil.rmtree(backup_root)
    backup_root.mkdir(parents=True)

    def write_json(path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        save_json(path, data)

    for u in users:
        uname = u["username"]
        user_dir = backup_root / "users" / uname
        user_customers = [c for c in customers if c.get("assigned_to") == uname or c.get("created_by") == uname]
        user_customer_names = {c.get("name") for c in user_customers}
        write_json(user_dir / "customers" / "customers.json", user_customers)
        write_json(user_dir / "inventory" / "inventory.json",
                   [i for i in inv if i.get("created_by") == uname or i.get("customer_name") in user_customer_names])
        write_json(user_dir / "transactions" / "transactions.json", [t for t in txns if t.get("by") == uname])
        write_json(user_dir / "billing" / "bills.json", [b for b in bills if b.get("created_by") == uname])
        user_files = [m for m in files_meta if m.get("uploaded_by") == uname]
        write_json(user_dir / "uploads" / "files_meta.json", user_files)
        for m in user_files:
            src = FILES_DIR / m.get("filename", "")
            if src.exists():
                (user_dir / "uploads" / "files").mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, user_dir / "uploads" / "files" / m.get("original_name", src.name))

    write_json(backup_root / "admin" / "settings.json", load_json(SETTINGS_FILE, default_settings()))
    write_json(backup_root / "admin" / "template_headers.json", load_json(TEMPL_HEADERS_FILE, default_template_headers()))
    write_json(backup_root / "admin" / "activity_logs.json", load_json(LOGS_FILE, []))
    if TEMPL_DIR.exists():
        shutil.copytree(TEMPL_DIR, backup_root / "admin" / "excel_templates", dirs_exist_ok=True)
    zip_path = shutil.make_archive(str(backup_root), "zip", backup_root)
    shutil.rmtree(backup_root)
    log_activity(request.current_user["username"], "Created backup", "Admin", Path(zip_path).name)
    return send_file(zip_path, as_attachment=True, download_name=Path(zip_path).name,
                     mimetype="application/zip")

# ── Reports (JSON) ─────────────────────────────────────────────────────────────
@app.route("/api/reports/movement", methods=["GET"])
@require_auth
def movement_report():
    cu = request.current_user
    txns = load_json(TRANSACTIONS_FILE, [])
    if cu["role"] != "Admin":
        txns = [t for t in txns if t.get("by") == cu["username"]]
    days = {}
    for t in txns:
        d = t.get("date") or t["datetime"][:10]
        days.setdefault(d, {"in": 0, "out": 0})
        if t["type"] == "IN":
            days[d]["in"] += t["qty"]
        else:
            days[d]["out"] += t["qty"]
    return jsonify(sorted(days.items()))


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'actlog',     label:'Activity Log', icon:'actlog',     module:'Activity Log' },
  { id:'templates',  label:'Templates',    icon:'templates',  module:'Templates', adminOnly:true },
  { id:'users',      label:'Users',        icon:'users',      module:'Users',      adminOnly:true },

async function renderReports() {
  setMain(`
    <div class="page-header">
      <div><h1>Reports</h1><div class="subtitle">View stock movement reports</div></div>
    </div>
    <div class="page-body">
      <div class="card" style="margin-bottom:20px">
        <div class="card-header"><h3>Filter Transactions</h3></div>
        <div class="card-body">
          <div class="field-row">
            <div class="field"><label>Date From</label><input id="r-from" type="date" value="${new Date(Date.now()-7*86400000).toISOString().slice(0,10)}"/></div>
            <div class="field"><label>Date To</label><input id="r-to" type="date" value="${new Date().toISOString().slice(0,10)}"/></div>
          </div>
          <button class="btn btn-accent" onclick="loadReport()">Run Report</button>
        </div>
      </div>
      <div id="report-result"></div>
    </div>`);
}

async function loadReport() {
  const from = document.getElementById('r-from').value;
  const to = document.getElementById('r-to').value;
  document.getElementById('report-result').innerHTML = loadingHtml();
  try {
    const txns = await API(`/transactions?limit=1000&date_from=${from}&date_to=${to}`);
    if (!txns.length) { document.getElementById('report-result').innerHTML = emptyHtml('No transactions in this range'); return; }
    const totalIn = txns.filter(t=>t.type==='IN').reduce((s,t)=>s+t.qty,0);
    const totalOut = txns.filter(t=>t.type==='OUT').reduce((s,t)=>s+t.qty,0);
    let html = `
      <div class="stat-grid" style="margin-bottom:16px">
        <div class="stat-card"><div class="stat-icon green">${icon.stockio}</div><div class="stat-label">Total Stock In</div><div class="stat-value">${fmt.num(totalIn)}</div></div>
        <div class="stat-card"><div class="stat-icon amber">${icon.stockio}</div><div class="stat-label">Total Stock Out</div><div class="stat-value">${fmt.num(totalOut)}</div></div>
        <div class="stat-card"><div class="stat-icon blue">${icon.reports}</div><div class="stat-label">Transactions</div><div class="stat-value">${fmt.num(txns.length)}</div></div>
      </div>
      <div class="card"><div class="table-wrap"><table>
        <thead><tr><th>Date</th><th>Type</th><th>SKU</th><th>Item</th><th>Customer</th><th>Qty</th><th>Reference</th><th>By</th></tr></thead><tbody>`;
    for (const t of txns) {
      html += `<tr><td>${fmt.date(t.date)}</td>
        <td>${badge(t.type,{IN:'badge-green',OUT:'badge-amber'})}</td>
        <td class="td-mono">${t.sku}</td><td>${t.name}</td>
        <td>${t.customer_name||'—'}</td><td class="fw700">${fmt.num(t.qty)}</td>
        <td class="td-mono">${t.ref||'—'}</td><td>${t.by}</td></tr>`;
    }
    html += `</tbody></table></div></div>`;
    document.getElementById('report-result').innerHTML = html;
  } catch(e) { document.getElementById('report-result').innerHTML=`<p class="text-danger">${e.message}</p>`; }
}

/* ═══════════════════════════════════════════════════════════════════════════
   EXPORT
═══════════════════════════════════════════════════════════════════════════ */
async function renderExport() {
  const isAdmin = currentUser.role==='Admin';
  let userSection = '';
  if (isAdmin) {
    let users = [];
    try { users = await API('/users'); } catch(e){}
    const userOpts = users.map(u=>`<option value="${u.username}">${u.name} (@${u.username})</option>`).join('');
    userSection = `
      <div class="card">
        <div class="card-header"><h3>Per-User Report</h3></div>
        <div class="card-body">
          <div class="field-row">
            <div class="field"><label>User</label><select id="exp-user">${userOpts}</select></div>
            <div class="field"><label>Range</label><select id="exp-user-range"><option value="day">Today</option><option value="week" selected>This Week</option><option value="custom">Custom</option></select></div>
          </div>
          <div class="field-row">
            <div class="field"><label>From</label><input id="exp-user-from" type="date" value="${new Date(Date.now()-7*86400000).toISOString().slice(0,10)}"/></div>
            <div class="field"><label>To</label><input id="exp-user-to" type="date" value="${new Date().toISOString().slice(0,10)}"/></div>
          </div>
          <a id="exp-user-link" href="#" class="btn btn-accent" onclick="triggerUserExport(event)">${icon.export} Download User Report</a>
        </div>
      </div>
      <div class="card" style="margin-top:16px">
        <div class="card-header"><h3>All Users Summary</h3></div>
        <div class="card-body">
          <p class="text-muted" style="margin-bottom:12px">Export a combined Excel workbook with all users' activity.</p>
          <div class="field-row">
            <div class="field"><label>Range</label><select id="exp-all-range"><option value="day">Today</option><option value="week" selected>This Week</option><option value="custom">Custom</option></select></div>
            <div class="field"><label>From</label><input id="exp-all-from" type="date" value="${new Date(Date.now()-7*86400000).toISOString().slice(0,10)}"/></div>
            <div class="field"><label>To</label><input id="exp-all-to" type="date" value="${new Date().toISOString().slice(0,10)}"/></div>
          </div>
          <a href="#" class="btn btn-accent" onclick="triggerAllUsersExport(event)">${icon.export} Download All-Users Report</a>
        </div>
      </div>`;
  }

  setMain(`
    <div class="page-header">
      <div><h1>Export</h1><div class="subtitle">Download Excel reports</div></div>
    </div>
    <div class="page-body">
      <div class="card" style="margin-bottom:16px">
        <div class="card-header"><h3>My Report</h3></div>
        <div class="card-body">
          <div class="field-row">
            <div class="field"><label>Range</label><select id="exp-range"><option value="day">Today</option><option value="week" selected>This Week</option><option value="custom">Custom</option></select></div>
            <div class="field"><label>From</label><input id="exp-from" type="date" value="${new Date(Date.now()-7*86400000).toISOString().slice(0,10)}"/></div>
            <div class="field"><label>To</label><input id="exp-to" type="date" value="${new Date().toISOString().slice(0,10)}"/></div>
          </div>
          <a href="#" class="btn btn-accent" onclick="triggerExport(event)">${icon.export} Download My Report</a>
        </div>
      </div>
      ${userSection}
    </div>`);
}

function triggerExport(e) {
  e.preventDefault();
  const range = document.getElementById('exp-range').value;
  const from = document.getElementById('exp-from').value;
  const to = document.getElementById('exp-to').value;
  const token = localStorage.getItem('wms_token');
  let url = `/api/export/report?range=${range}&date_from=${from}&date_to=${to}`;
  // Use fetch + blob for auth header
  fetch(url, {headers:{Authorization:`Bearer ${token}`}}).then(r=>r.blob()).then(blob=>{
    const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
    a.download=`report_${range}_${from}.xlsx`; a.click();
    toast('Report downloaded','success');
  }).catch(e=>toast(e.message,'error'));
}

function triggerUserExport(e) {
  e.preventDefault();
  const u = document.getElementById('exp-user').value;
  const range = document.getElementById('exp-user-range').value;
  const from = document.getElementById('exp-user-from').value;
  const to = document.getElementById('exp-user-to').value;
  const token = localStorage.getItem('wms_token');
  fetch(`/api/export/report/user/${u}?range=${range}&date_from=${from}&date_to=${to}`, {headers:{Authorization:`Bearer ${token}`}})
    .then(r=>r.blob()).then(blob=>{
      const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
      a.download=`report_${u}_${range}.xlsx`; a.click();
      toast('User report downloaded','success');
    }).catch(e=>toast(e.message,'error'));
}

function triggerAllUsersExport(e) {
  e.preventDefault();
  const range = document.getElementById('exp-all-range').value;
  const from = document.getElementById('exp-all-from').value;
  const to = document.getElementById('exp-all-to').value;
  const token = localStorage.getItem('wms_token');
  fetch(`/api/export/report/all-users-summary?range=${range}&date_from=${from}&date_to=${to}`, {headers:{Authorization:`Bearer ${token}`}})
    .then(r=>r.blob()).then(blob=>{
      const a=document.createElement('a'); a.href=URL.createObjectURL(blob);
      a.download=`all_users_summary_${range}.xlsx`; a.click();
      toast('All-users report downloaded','success');
    }).catch(e=>toast(e.message,'error'));
}

/* ═══════════════════════════════════════════════════════════════════════════
   AUTH
═══════════════════════════════════════════════════════════════════════════ */
async function doLogin() {
  const un = document.getElementById('login-username').value.trim();
  const pw = document.getElementById('login-password').value;
  const errEl = document.getElementById('login-error');
  const btn = document.getElementById('login-btn');
  if (!un||!pw) { errEl.textContent='Enter username and password'; errEl.style.display='block'; return; }
  btn.disabled=true; btn.textContent='Signing in…';
  try {
    const data = await fetch('/api/auth/login', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({username:un,password:pw})
    }).then(async r=>{ const d=await r.json(); if(!r.ok) throw new Error(d.error||'Login failed'); return d; });
    localStorage.setItem('wms_token', data.token);
    currentUser = data.user;
    launchApp();
  } catch(e) {
    errEl.textContent = e.message; errEl.style.display='block';
    btn.disabled=false; btn.textContent='Sign in';
  }
"""
