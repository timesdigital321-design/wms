"""Billing routes for the WMS backend."""

from wms_core import *

@app.route("/api/bills", methods=["GET"])
@require_auth
def get_bills():
    cu = request.current_user
    bills = load_json(BILLS_FILE, [])
    if cu["role"] != "Admin":
        bills = [b for b in bills if b.get("created_by") == cu["username"]]
    status = request.args.get("status", "")
    if status:
        bills = [b for b in bills if b["status"] == status]
    return jsonify(bills[::-1])

@app.route("/api/bills", methods=["POST"])
@require_auth
def create_bill():
    cu = request.current_user
    data = request.json or {}
    bills = load_json(BILLS_FILE, [])
    bill = {
        "id": str(uuid.uuid4()),
        "num": data.get("num", f"BILL-{str(len(bills)+1).zfill(4)}"),
        "date": data.get("date", today_str()),
        "customer": data.get("customer", ""),
        "items": data.get("items", []),
        "amount": float(data.get("amount", 0)),
        "status": "Pending",
        "notes": data.get("notes", ""),
        "created_by": cu["username"],
        "created_at": now_str()
    }
    bills.append(bill)
    save_json(BILLS_FILE, bills)
    log_activity(cu["username"], "Created bill", "Billing",
                 f"{bill['num']} — {bill['customer']} — {bill['amount']}")
    return jsonify(bill), 201

@app.route("/api/bills/<bid>", methods=["PUT"])
@require_auth
def update_bill(bid):
    cu = request.current_user
    data = request.json or {}
    bills = load_json(BILLS_FILE, [])
    bill = next((b for b in bills if b["id"] == bid), None)
    if not bill:
        return jsonify({"error": "Bill not found"}), 404
    if cu["role"] != "Admin" and bill.get("created_by") != cu["username"]:
        return jsonify({"error": "Access denied"}), 403
    for field in ["status", "notes", "amount", "customer"]:
        if field in data:
            bill[field] = data[field]
    save_json(BILLS_FILE, bills)
    log_activity(cu["username"], "Updated bill", "Billing",
                 f"{bill['num']} — {bill['status']}")
    return jsonify(bill)

@app.route("/api/bills/summary", methods=["GET"])
@require_auth
def bill_summary():
    cu = request.current_user
    bills = load_json(BILLS_FILE, [])
    if cu["role"] != "Admin":
        bills = [b for b in bills if b.get("created_by") == cu["username"]]
    return jsonify({
        "total": sum(b["amount"] for b in bills),
        "paid": sum(b["amount"] for b in bills if b["status"] == "Paid"),
        "pending": sum(b["amount"] for b in bills if b["status"] == "Pending"),
        "overdue": sum(b["amount"] for b in bills if b["status"] == "Overdue"),
        "count": len(bills)
    })

@app.route("/api/bills/export", methods=["GET"])
@require_auth
def export_bills_excel():
    cu = request.current_user
    bills = load_json(BILLS_FILE, [])
    if cu["role"] != "Admin":
        bills = [b for b in bills if b.get("created_by") == cu["username"]]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Billing"
    headers = ["Bill No", "Date", "Customer", "Amount", "Status", "Created By", "Notes"]
    ws.append(headers)
    for c in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=c)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="1F4E78")
        cell.alignment = Alignment(horizontal="center")
    for b in bills:
        ws.append([
            b.get("num", ""), b.get("date", ""), b.get("customer", ""),
            b.get("amount", 0), b.get("status", ""), b.get("created_by", ""),
            b.get("notes", "")
        ])
    for col in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col)].width = 18
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    log_activity(cu["username"], "Downloaded billing export", "File Log",
                 "billing_export.xlsx", meta={"file_type": "billing", "file_status": "done", "direction": "download"})
    return send_file(buf, as_attachment=True,
                     download_name=f"billing_export_{today_str()}.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'billing',    label:'Billing',      icon:'billing',    module:'Billing' },
  { id:'customers',  label:'Customers',    icon:'customers',  module:'Customers' },

async function renderBilling() {
  setMain(`
    <div class="page-header">
      <div><h1>Billing</h1><div class="subtitle">Invoice and payment tracking</div></div>
      <div class="header-actions">
        <button class="btn btn-accent btn-sm" onclick="openAddBill()">${icon.plus} New Bill</button>
      </div>
    </div>
    <div class="page-body" id="billing-body">${loadingHtml()}</div>`);
  try {
    const [bills, summary] = await Promise.all([API('/bills'), API('/bills/summary')]);
    let html = `
    <div class="stat-grid" style="margin-bottom:20px">
      <div class="stat-card"><div class="stat-icon blue">${icon.billing}</div><div class="stat-label">Total Bills</div><div class="stat-value">${fmt.num(summary.count)}</div></div>
      <div class="stat-card"><div class="stat-icon green">${icon.reports}</div><div class="stat-label">Total Amount</div><div class="stat-value" style="font-size:18px">${fmt.sar(summary.total)}</div></div>
      <div class="stat-card"><div class="stat-icon green">${icon.reports}</div><div class="stat-label">Paid</div><div class="stat-value" style="font-size:20px;color:var(--green)">${fmt.sar(summary.paid)}</div></div>
      <div class="stat-card"><div class="stat-icon amber">${icon.billing}</div><div class="stat-label">Pending</div><div class="stat-value" style="font-size:20px;color:var(--amber)">${fmt.sar(summary.pending)}</div></div>
      <div class="stat-card"><div class="stat-icon red">${icon.warning}</div><div class="stat-label">Overdue</div><div class="stat-value" style="font-size:20px;color:var(--red)">${fmt.sar(summary.overdue)}</div></div>
    </div>
    <div class="card"><div class="table-wrap">`;
    if (!bills.length) { html += emptyHtml('No bills yet','Create your first bill to get started'); }
    else {
      html += `<table><thead><tr><th>Bill #</th><th>Date</th><th>Customer</th><th>Amount</th><th>Status</th><th>Created By</th><th></th></tr></thead><tbody>`;
      for (const b of bills) {
        html += `<tr>
          <td class="td-mono fw700">${b.num}</td>
          <td>${fmt.date(b.date)}</td>
          <td class="fw700">${b.customer}</td>
          <td class="nowrap fw700">${fmt.sar(b.amount)}</td>
          <td>${badge(b.status,{Paid:'badge-green',Pending:'badge-amber',Overdue:'badge-red'})}</td>
          <td>${b.created_by}</td>
          <td class="nowrap">
            <button class="btn btn-ghost btn-icon btn-sm" onclick='editBill(${JSON.stringify(b)})'>${icon.edit}</button>
          </td></tr>`;
      }
      html += `</tbody></table>`;
    }
    html += `</div></div>`;
    document.getElementById('billing-body').innerHTML = html;
  } catch(e) { document.getElementById('billing-body').innerHTML = `<p class="text-danger">${e.message}</p>`; }
}

async function openAddBill() {
  openModal('New Bill', `
    <div class="field-row">
      <div class="field"><label>Bill Number</label><input id="b-num" placeholder="BILL-0001"/></div>
      <div class="field"><label>Date</label><input id="b-date" type="date" value="${new Date().toISOString().slice(0,10)}"/></div>
    </div>
    <div class="field"><label>Customer *</label><input id="b-cust" placeholder="Customer name"/></div>
    <div class="field-row">
      <div class="field"><label>Amount (SAR) *</label><input id="b-amt" type="number" step="0.01" min="0" value="0"/></div>
      <div class="field"><label>Items Count</label><input id="b-items" type="number" min="0" value="0"/></div>
    </div>
    <div class="field"><label>Notes</label><textarea id="b-notes" rows="2"></textarea></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="saveBill()">Create Bill</button>`);
}

async function saveBill() {
  const body = {
    num: document.getElementById('b-num').value,
    date: document.getElementById('b-date').value,
    customer: document.getElementById('b-cust').value.trim(),
    amount: +document.getElementById('b-amt').value,
    items: +document.getElementById('b-items').value,
    notes: document.getElementById('b-notes').value,
  };
  if (!body.customer) { toast('Customer is required','error'); return; }
  try {
    await API('/bills', {method:'POST', body:JSON.stringify(body)});
    toast('Bill created','success'); closeModal(); renderBilling();
  } catch(e) { toast(e.message,'error'); }
}

async function editBill(bill) {
  openModal('Edit Bill', `
    <div class="field"><label>Bill #</label><input value="${bill.num}" readonly style="background:var(--surface)"/></div>
    <div class="field"><label>Customer</label><input id="be-cust" value="${bill.customer}"/></div>
    <div class="field"><label>Amount (SAR)</label><input id="be-amt" type="number" step="0.01" value="${bill.amount}"/></div>
    <div class="field"><label>Status</label><select id="be-status">
      <option ${bill.status==='Pending'?'selected':''}>Pending</option>
      <option ${bill.status==='Paid'?'selected':''}>Paid</option>
      <option ${bill.status==='Overdue'?'selected':''}>Overdue</option>
    </select></div>
    <div class="field"><label>Notes</label><textarea id="be-notes" rows="2">${bill.notes||''}</textarea></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="updateBill('${bill.id}')">Save</button>`);
}

async function updateBill(id) {
  const body = {
    customer: document.getElementById('be-cust').value,
    amount: +document.getElementById('be-amt').value,
    status: document.getElementById('be-status').value,
    notes: document.getElementById('be-notes').value,
  };
  try {
    await API(`/bills/${id}`, {method:'PUT', body:JSON.stringify(body)});
    toast('Bill updated','success'); closeModal(); renderBilling();
  } catch(e) { toast(e.message,'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   CUSTOMERS
═══════════════════════════════════════════════════════════════════════════ */
"""
