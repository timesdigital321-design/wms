"""Stock Io routes for the WMS backend."""

from wms_core import *

@app.route("/api/transactions", methods=["GET"])
@require_auth
def get_transactions():
    cu = request.current_user
    txns = load_json(TRANSACTIONS_FILE, [])
    if cu["role"] != "Admin":
        txns = [t for t in txns if t.get("by") == cu["username"]]
    t_type = request.args.get("type", "")
    customer = request.args.get("customer", "")
    date_from = request.args.get("date_from", "")
    date_to = request.args.get("date_to", "")
    if t_type:
        txns = [t for t in txns if t["type"] == t_type.upper()]
    if customer:
        txns = [t for t in txns if t.get("customer_name", "") == customer]
    if date_from:
        txns = [t for t in txns if t.get("date", t["datetime"][:10]) >= date_from]
    if date_to:
        txns = [t for t in txns if t.get("date", t["datetime"][:10]) <= date_to]
    limit = int(request.args.get("limit", 200))
    return jsonify(txns[-limit:][::-1])

@app.route("/api/transactions", methods=["POST"])
@require_auth
def add_transaction():
    cu = request.current_user
    data = request.json or {}
    txn_type = data.get("type", "").upper()
    if txn_type not in ["IN", "OUT"]:
        return jsonify({"error": "type must be IN or OUT"}), 400
    sku = data.get("sku", "").upper()
    qty = int(data.get("qty", 0))
    if qty <= 0:
        return jsonify({"error": "qty must be > 0"}), 400
    customer_name = data.get("customer_name", data.get("party", ""))
    if not customer_name:
        return jsonify({"error": "Customer name is required"}), 400
    inv = load_json(INVENTORY_FILE, [])
    item = next((i for i in inv if (i.get("id") == sku or i.get("sku") == sku) and i.get("customer_name", "") == customer_name), None)
    if not item:
        return jsonify({"error": f"Item {sku} not found for customer {customer_name}"}), 404
    # Non-admins may only move stock for items tied to one of their own customers
    if not user_owns_inventory_item(cu, item):
        return jsonify({"error": "Access denied for this item"}), 403
    if txn_type == "OUT":
        if item["qty"] < qty:
            return jsonify({"error": f"Insufficient stock. Available: {item['qty']}"}), 409
        item["qty"] -= qty
    else:
        item["qty"] += qty
    item["updated"] = today_str()
    save_json(INVENTORY_FILE, inv)
    txns = load_json(TRANSACTIONS_FILE, [])
    txn = {
        "id": str(uuid.uuid4()), "datetime": now_str(),
        "date": data.get("date", today_str()),
        "type": txn_type, "sku": item.get("sku", sku), "name": item["name"],
        "customer_id": data.get("customer_id", item.get("customer_id", "")),
        "customer_name": customer_name or item.get("customer_name", ""),
        "qty": qty, "ref": data.get("ref", "MANUAL"),
        "by": cu["username"], "status": "Completed",
        "notes": data.get("notes", "")
    }
    txns.append(txn)
    save_json(TRANSACTIONS_FILE, txns)
    log_activity(cu["username"], f"Stock {txn_type}", "Stock In/Out",
                 f"{sku} qty:{qty} customer:{txn['customer_name']}")
    return jsonify(txn), 201

# ── Bulk Stock In/Out ──────────────────────────────────────────────────────────
@app.route("/api/transactions/bulk", methods=["POST"])
@require_auth
def bulk_transaction():
    """
    Bulk Stock In or Out for multiple items at once.
    Body: {
      "type": "IN"|"OUT",
      "customer_name": "...",
      "ref": "...",
      "date": "...",
      "notes": "...",
      "items": [ { "sku": "...", "qty": N }, ... ]
    }
    """
    cu = request.current_user
    data = request.json or {}
    txn_type = data.get("type", "").upper()
    if txn_type not in ["IN", "OUT"]:
        return jsonify({"error": "type must be IN or OUT"}), 400
    items_data = data.get("items", [])
    if not items_data:
        return jsonify({"error": "items list is required"}), 400
    customer_name = data.get("customer_name", data.get("party", ""))
    if not customer_name:
        return jsonify({"error": "Customer name is required"}), 400
    ref = data.get("ref", "BULK")
    date = data.get("date", today_str())
    notes = data.get("notes", "")
    inv = load_json(INVENTORY_FILE, [])
    txns = load_json(TRANSACTIONS_FILE, [])
    customers = load_json(CUSTOMERS_FILE, [])
    results = []
    errors = []
    for row in items_data:
        sku = (row.get("sku") or "").upper()
        qty = int(row.get("qty", 0))
        if not sku or qty <= 0:
            errors.append(f"Invalid row: sku={sku}, qty={qty}")
            continue
        item = next((i for i in inv if (i.get("id") == sku or i.get("sku") == sku) and i.get("customer_name", "") == customer_name), None)
        if not item:
            errors.append(f"{sku}: not found for customer {customer_name}")
            continue
        if not user_owns_inventory_item(cu, item, customers):
            errors.append(f"{sku}: access denied — not one of your customers")
            continue
        if txn_type == "OUT" and item["qty"] < qty:
            errors.append(f"{sku}: insufficient stock (have {item['qty']}, need {qty})")
            continue
        if txn_type == "OUT":
            item["qty"] -= qty
        else:
            item["qty"] += qty
        item["updated"] = today_str()
        txn = {
            "id": str(uuid.uuid4()), "datetime": now_str(), "date": date,
            "type": txn_type, "sku": item.get("sku", sku), "name": item["name"],
            "customer_id": data.get("customer_id", item.get("customer_id", "")),
            "customer_name": customer_name or item.get("customer_name", ""),
            "qty": qty, "ref": ref, "by": cu["username"],
            "status": "Completed", "notes": notes
        }
        txns.append(txn)
        results.append(txn)
    save_json(INVENTORY_FILE, inv)
    save_json(TRANSACTIONS_FILE, txns)
    log_activity(cu["username"], f"Bulk Stock {txn_type}", "Stock In/Out",
                 f"{len(results)} items processed, {len(errors)} errors — customer:{customer_name}")
    return jsonify({"processed": len(results), "errors": errors, "transactions": results}), 201


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'stockio',    label:'Stock In/Out', icon:'stockio',    module:'Stock In/Out' },
  { id:'billing',    label:'Billing',      icon:'billing',    module:'Billing' },

async function renderStockIO() {
  setMain(`
    <div class="page-header">
      <div><h1>Stock In / Out</h1><div class="subtitle">Record and track stock movements</div></div>
      <div class="header-actions">
        <button class="btn btn-green btn-sm" onclick="openStockModal('IN')">${icon.plus} Stock In</button>
        <button class="btn btn-danger btn-sm" onclick="openStockModal('OUT')">${icon.plus} Stock Out</button>
        <button class="btn btn-ghost btn-sm" onclick="openBulkStockModal()">${icon.edit} Bulk</button>
      </div>
    </div>
    <div class="page-body">
      <div class="toolbar">
        <div class="search-box"><span class="search-icon">${icon.search}</span><input id="txn-search" placeholder="Search item or reference…" oninput="filterTxns()"/></div>
        <select class="filter-select" id="txn-type-filter" onchange="filterTxns()">
          <option value="">All Types</option><option value="IN">Stock In</option><option value="OUT">Stock Out</option>
        </select>
      </div>
      <div class="card"><div class="table-wrap" id="txn-table">${loadingHtml()}</div></div>
    </div>`);
  await loadTxns();
}

let txnData = [];
async function loadTxns() {
  try {
    txnData = await API('/transactions?limit=300');
    renderTxnTable();
  } catch(e) { document.getElementById('txn-table').innerHTML=`<p class="text-danger" style="padding:20px">${e.message}</p>`; }
}

function filterTxns() { renderTxnTable(); }
function renderTxnTable() {
  const q = (document.getElementById('txn-search')||{}).value?.toLowerCase()||'';
  const t = (document.getElementById('txn-type-filter')||{}).value||'';
  let rows = txnData.filter(r =>
    (!q || (r.name||'').toLowerCase().includes(q) || (r.sku||'').toLowerCase().includes(q) || (r.ref||'').toLowerCase().includes(q)) &&
    (!t || r.type===t)
  );
  if (!rows.length) { document.getElementById('txn-table').innerHTML = emptyHtml('No transactions found'); return; }
  let html = `<table><thead><tr><th>Date</th><th>Type</th><th>SKU</th><th>Item</th><th>Customer</th><th>Qty</th><th>Reference</th><th>By</th><th>Status</th></tr></thead><tbody>`;
  for (const r of rows) {
    html += `<tr>
      <td class="nowrap">${fmt.date(r.date||r.datetime)}</td>
      <td>${badge(r.type, {IN:'badge-green',OUT:'badge-amber'})}</td>
      <td class="td-mono">${r.sku}</td>
      <td class="fw700">${r.name}</td>
      <td>${r.customer_name||'—'}</td>
      <td class="fw700">${fmt.num(r.qty)}</td>
      <td class="td-mono">${r.ref||'—'}</td>
      <td>${r.by}</td>
      <td>${badge(r.status,{Completed:'badge-green',Pending:'badge-amber'})}</td></tr>`;
  }
  html += `</tbody></table>`;
  document.getElementById('txn-table').innerHTML = html;
}

async function openStockModal(type) {
  const [inv, custNames] = await Promise.all([API('/inventory'), API('/customers/names')]);
  const invOpts = inv.map(i=>`<option value="${i.sku}">${i.sku} — ${i.name} (${i.customer_name||'?'}) [Qty:${i.qty}]</option>`).join('');
  const custOpts = custNames.map(c=>`<option>${c}</option>`).join('');
  const isIN = type==='IN';
  openModal(`Stock ${type} — Single Item`, `
    <div class="field"><label>Item (SKU) *</label><select id="s-sku"><option value="">— Select Item —</option>${invOpts}</select></div>
    <div class="field-row">
      <div class="field"><label>Quantity *</label><input id="s-qty" type="number" value="1" min="1"/></div>
      <div class="field"><label>Customer</label><select id="s-cust"><option value="">— Select —</option>${custOpts}</select></div>
    </div>
    <div class="field-row">
      <div class="field"><label>Reference</label><input id="s-ref" placeholder="${isIN?'PO-2024-001':'DO-2024-001'}"/></div>
      <div class="field"><label>Date</label><input id="s-date" type="date" value="${new Date().toISOString().slice(0,10)}"/></div>
    </div>
    ${isIN?`<div class="field"><label>Unit Cost (SAR)</label><input id="s-cost" type="number" step="0.01" value="0" min="0" placeholder="Optional"/></div>`:''}
    <div class="field"><label>Notes</label><textarea id="s-notes" rows="2"></textarea></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn ${isIN?'btn-green':'btn-danger'}" onclick="saveStock('${type}')">Confirm ${type}</button>`);
}

async function saveStock(type) {
  const sku = document.getElementById('s-sku').value;
  const qty = +document.getElementById('s-qty').value;
  if (!sku) { toast('Select an item','error'); return; }
  if (qty<=0) { toast('Quantity must be > 0','error'); return; }
  const body = {
    type, sku, qty,
    customer_name: document.getElementById('s-cust').value,
    ref: document.getElementById('s-ref').value,
    date: document.getElementById('s-date').value,
    notes: document.getElementById('s-notes').value,
  };
  if (type==='IN' && document.getElementById('s-cost')) body.unit_cost = +document.getElementById('s-cost').value;
  try {
    await API('/transactions', {method:'POST', body:JSON.stringify(body)});
    toast(`Stock ${type} recorded`, 'success'); closeModal(); loadTxns();
  } catch(e) { toast(e.message,'error'); }
}

async function openBulkStockModal() {
  const [inv, custNames] = await Promise.all([API('/inventory'), API('/customers/names')]);
  const custOpts = custNames.map(c=>`<option>${c}</option>`).join('');
  let rows = inv.map(i=>`
    <tr>
      <td><input type="checkbox" class="bulk-check" value="${i.sku}"/></td>
      <td class="td-mono">${i.sku}</td><td>${i.name}</td>
      <td>${i.customer_name||'—'}</td><td>${fmt.num(i.qty)}</td>
      <td><input type="number" class="bulk-qty" data-sku="${i.sku}" min="1" value="1" style="width:70px;padding:4px 7px;border:1.5px solid var(--surface-3);border-radius:6px;"/></td>
    </tr>`).join('');
  openModal('Bulk Stock In / Out', `
    <div class="field-row" style="margin-bottom:14px">
      <div class="field"><label>Type *</label><select id="bs-type"><option value="IN">Stock In</option><option value="OUT">Stock Out</option></select></div>
      <div class="field"><label>Customer</label><select id="bs-cust"><option value="">— Select —</option>${custOpts}</select></div>
    </div>
    <div class="field-row" style="margin-bottom:16px">
      <div class="field"><label>Reference</label><input id="bs-ref" placeholder="BULK-001"/></div>
      <div class="field"><label>Date</label><input id="bs-date" type="date" value="${new Date().toISOString().slice(0,10)}"/></div>
    </div>
    <div class="table-wrap" style="max-height:320px;overflow-y:auto">
    <table><thead><tr><th></th><th>SKU</th><th>Item</th><th>Customer</th><th>Available</th><th>Qty</th></tr></thead><tbody>${rows}</tbody></table>
    </div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="saveBulkStock()">Submit Bulk</button>`, true);
}

async function saveBulkStock() {
  const type = document.getElementById('bs-type').value;
  const ref = document.getElementById('bs-ref').value||'BULK';
  const date = document.getElementById('bs-date').value;
  const cust = document.getElementById('bs-cust').value;
  const items = [];
  document.querySelectorAll('.bulk-check:checked').forEach(cb => {
    const qty = +document.querySelector(`.bulk-qty[data-sku="${cb.value}"]`).value;
    if (qty>0) items.push({sku:cb.value, qty});
  });
  if (!items.length) { toast('Select at least one item','error'); return; }
  try {
    const r = await API('/transactions/bulk', {method:'POST', body:JSON.stringify({type,ref,date,customer_name:cust,items})});
    toast(`Processed ${r.processed} items${r.errors?.length?`, ${r.errors.length} errors`:''}`,'success');
    closeModal(); loadTxns();
  } catch(e) { toast(e.message,'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   BILLING
═══════════════════════════════════════════════════════════════════════════ */
"""
