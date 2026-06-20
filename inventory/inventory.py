"""Inventory routes for the WMS backend."""

from wms_core import *

# Inventory items are now linked to a customer. Browsing is by customer.
# Stock In/Out also references the customer.

@app.route("/api/inventory", methods=["GET"])
@require_auth
def get_inventory():
    cu = request.current_user
    inv = load_json(INVENTORY_FILE, [])

    # Non-admins see only inventory for their customers
    if cu["role"] != "Admin":
        my_customers = {c["name"] for c in load_json(CUSTOMERS_FILE, [])
                        if c.get("assigned_to") == cu["username"]}
        inv = [i for i in inv if i.get("customer_name", "") in my_customers
               or i.get("created_by") == cu["username"]]

    q = request.args.get("q", "").lower()
    customer = request.args.get("customer", "")
    if q:
        inv = [i for i in inv if q in i["name"].lower() or q in i.get("sku", "").lower()]
    if customer:
        inv = [i for i in inv if i.get("customer_name", "") == customer]

    return jsonify(inv)

@app.route("/api/inventory", methods=["POST"])
@require_auth
def add_inventory_item():
    cu = request.current_user
    data = request.json or {}
    inv = load_json(INVENTORY_FILE, [])
    sku = data.get("sku", "").upper()
    # Non-admins may only create inventory under one of their own customers
    customer_id, customer_name, err = resolve_customer_for_user(
        cu, data.get("customer_id", ""), data.get("customer_name", ""))
    if err:
        return err
    if not customer_name:
        return jsonify({"error": "Customer name is required"}), 400
    if sku and any(i["sku"] == sku and i.get("customer_name", "") == customer_name for i in inv):
        return jsonify({"error": "SKU already exists for this customer"}), 409
    item = {
        "id": str(uuid.uuid4()),
        "sku": sku or f"SKU-{uuid.uuid4().hex[:6].upper()}",
        "name": data.get("name", ""),
        "customer_id": customer_id,
        "customer_name": customer_name,
        "qty": int(data.get("qty", 0)),
        "unit": data.get("unit", "PCS"),
        "min_level": int(data.get("min_level", 0)),
        "location": data.get("location", ""),
        "unit_cost": float(data.get("unit_cost", 0)),
        "updated": today_str(),
        "created_by": cu["username"]
    }
    inv.append(item)
    save_json(INVENTORY_FILE, inv)
    log_activity(cu["username"], "Added inventory item", "Inventory",
                 f"{item['sku']} — {item['name']} (customer: {item['customer_name']})")
    return jsonify(item), 201

@app.route("/api/inventory/<item_id>", methods=["PUT"])
@require_auth
def update_inventory_item(item_id):
    cu = request.current_user
    data = request.json or {}
    inv = load_json(INVENTORY_FILE, [])
    # Support both id and sku lookup
    item = next((i for i in inv if i.get("id") == item_id or i.get("sku") == item_id), None)
    if not item:
        return jsonify({"error": "Item not found"}), 404
    if not user_owns_inventory_item(cu, item):
        return jsonify({"error": "Access denied"}), 403
    # Non-admins can only reassign an item to one of their own customers
    if cu["role"] != "Admin" and ("customer_id" in data or "customer_name" in data):
        new_id, new_name, err = resolve_customer_for_user(
            cu, data.get("customer_id", ""), data.get("customer_name", ""))
        if err:
            return err
        data = {**data, "customer_id": new_id, "customer_name": new_name}
    for field in ["name", "customer_id", "customer_name", "qty", "unit",
                  "min_level", "location", "unit_cost"]:
        if field in data:
            item[field] = data[field]
    item["updated"] = today_str()
    save_json(INVENTORY_FILE, inv)
    log_activity(cu["username"], "Updated inventory item", "Inventory",
                 f"{item.get('sku')} — {item['name']}")
    return jsonify(item)

@app.route("/api/inventory/<item_id>", methods=["DELETE"])
@require_admin
def delete_inventory_item(item_id):
    inv = load_json(INVENTORY_FILE, [])
    target = next((i for i in inv if i.get("id") == item_id or i.get("sku") == item_id), None)
    inv = [i for i in inv if i.get("id") != item_id and i.get("sku") != item_id]
    if target is None:
        return jsonify({"error": "Item not found"}), 404
    save_json(INVENTORY_FILE, inv)
    log_activity(request.current_user["username"], "Deleted inventory item", "Inventory",
                 f"{target.get('sku')} — {target['name']}")
    return jsonify({"message": "Item deleted"})

# ── Bulk Inventory Operations ─────────────────────────────────────────────────
@app.route("/api/inventory/bulk-update", methods=["POST"])
@require_auth
def bulk_update_inventory():
    """
    Bulk edit multiple inventory items.
    Body: { "item_ids": [...], "update": { fields to apply to all } }
    Non-admins may only touch items they created or that belong to one of their
    own customers, and may only reassign items to one of their own customers.
    """
    cu = request.current_user
    data = request.json or {}
    item_ids = data.get("item_ids", [])
    update_fields = data.get("update", {})
    if not item_ids or not update_fields:
        return jsonify({"error": "item_ids and update fields are required"}), 400

    allowed_fields = ["customer_id", "customer_name", "unit", "min_level", "location", "unit_cost"]
    customers = load_json(CUSTOMERS_FILE, [])

    # Validate any customer reassignment once, up front
    resolved_customer_id, resolved_customer_name = None, None
    if "customer_id" in update_fields or "customer_name" in update_fields:
        resolved_customer_id, resolved_customer_name, err = resolve_customer_for_user(
            cu, update_fields.get("customer_id", ""), update_fields.get("customer_name", ""), customers)
        if err:
            return err

    inv = load_json(INVENTORY_FILE, [])
    updated_count = 0
    skipped = 0
    for item in inv:
        if item.get("id") in item_ids or item.get("sku") in item_ids:
            if not user_owns_inventory_item(cu, item, customers):
                skipped += 1
                continue
            for field in allowed_fields:
                if field == "customer_id" and resolved_customer_id is not None:
                    item[field] = resolved_customer_id
                elif field == "customer_name" and resolved_customer_name is not None:
                    item[field] = resolved_customer_name
                elif field in update_fields and field not in ("customer_id", "customer_name"):
                    item[field] = update_fields[field]
            item["updated"] = today_str()
            updated_count += 1
    save_json(INVENTORY_FILE, inv)
    log_activity(cu["username"], "Bulk updated inventory", "Inventory",
                 f"{updated_count} updated, {skipped} skipped (no access) — fields: {', '.join(update_fields.keys())}")
    return jsonify({"updated": updated_count, "skipped": skipped})

@app.route("/api/inventory/bulk-delete", methods=["POST"])
@require_admin
def bulk_delete_inventory():
    """
    Bulk delete inventory items.
    Body: { "item_ids": [...] }
    """
    data = request.json or {}
    item_ids = set(data.get("item_ids", []))
    if not item_ids:
        return jsonify({"error": "item_ids required"}), 400
    inv = load_json(INVENTORY_FILE, [])
    before = len(inv)
    inv = [i for i in inv if i.get("id") not in item_ids and i.get("sku") not in item_ids]
    deleted = before - len(inv)
    save_json(INVENTORY_FILE, inv)
    log_activity(request.current_user["username"], "Bulk deleted inventory", "Inventory",
                 f"{deleted} items removed")
    return jsonify({"deleted": deleted})

@app.route("/api/inventory/summary", methods=["GET"])
@require_auth
def inventory_summary():
    cu = request.current_user
    inv = load_json(INVENTORY_FILE, [])
    if cu["role"] != "Admin":
        my_customers = {c["name"] for c in load_json(CUSTOMERS_FILE, [])
                        if c.get("assigned_to") == cu["username"]}
        inv = [i for i in inv if i.get("customer_name", "") in my_customers
               or i.get("created_by") == cu["username"]]
    low_stock = [i for i in inv if i["qty"] < i["min_level"]]
    total_value = sum(i["qty"] * i.get("unit_cost", 0) for i in inv)
    by_customer = {}
    for i in inv:
        c = i.get("customer_name", "Unknown")
        by_customer[c] = by_customer.get(c, 0) + 1
    return jsonify({
        "total_skus": len(inv),
        "total_value": round(total_value, 2),
        "low_stock_count": len(low_stock),
        "low_stock_items": low_stock,
        "by_customer": by_customer
    })


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'inventory',  label:'Inventory',    icon:'inventory',  module:'Inventory' },
  { id:'stockio',    label:'Stock In/Out', icon:'stockio',    module:'Stock In/Out' },

async function renderInventory() {
  setMain(`
    <div class="page-header">
      <div><h1>Inventory</h1><div class="subtitle">Customer-centric stock management</div></div>
      <div class="header-actions">
        <button class="btn btn-ghost btn-sm" onclick="renderInventory()">${icon.refresh} Refresh</button>
        <button class="btn btn-accent btn-sm" onclick="openAddInventory()">${icon.plus} Add Item</button>
      </div>
    </div>
    <div class="page-body">
      <div class="toolbar">
        <div class="search-box"><span class="search-icon">${icon.search}</span><input id="inv-search" placeholder="Search SKU or item name…" oninput="filterInventory()"/></div>
        <select class="filter-select" id="inv-cust-filter" onchange="filterInventory()"><option value="">All Customers</option></select>
        ${currentUser.role==='Admin'?`<button class="btn btn-ghost btn-sm" onclick="openBulkEdit()">${icon.edit} Bulk Edit</button>
        <button class="btn btn-danger btn-sm" onclick="openBulkDelete()">Bulk Delete</button>`:''}
      </div>
      <div class="bulk-bar" id="inv-bulk-bar">
        <span class="bulk-count" id="inv-sel-count">0 selected</span>
        <button class="btn btn-ghost btn-sm" onclick="bulkEditSelected()">${icon.edit} Edit Selected</button>
        ${currentUser.role==='Admin'?`<button class="btn btn-danger btn-sm" onclick="bulkDeleteSelected()">Delete</button>`:''}
        <span class="bulk-spacer"></span>
        <button class="btn btn-ghost btn-sm" onclick="clearSelection()">Clear</button>
      </div>
      <div class="card"><div class="table-wrap" id="inv-table">${loadingHtml()}</div></div>
    </div>`);
  try {
    [invData, invCustomerNames] = await Promise.all([
      API('/inventory'),
      API('/customers/names')
    ]);
    const sel = document.getElementById('inv-cust-filter');
    for (const n of invCustomerNames) {
      const o = document.createElement('option'); o.value=n; o.textContent=n; sel.appendChild(o);
    }
    renderInvTable();
  } catch(e) { document.getElementById('inv-table').innerHTML = `<p class="text-danger" style="padding:20px">${e.message}</p>`; }
}

function filterInventory() {
  renderInvTable();
}

function renderInvTable() {
  const q = (document.getElementById('inv-search')||{}).value?.toLowerCase()||'';
  const cust = (document.getElementById('inv-cust-filter')||{}).value||'';
  let rows = invData.filter(i =>
    (!q || i.name.toLowerCase().includes(q) || (i.sku||'').toLowerCase().includes(q)) &&
    (!cust || i.customer_name === cust)
  );
  if (!rows.length) { document.getElementById('inv-table').innerHTML = emptyHtml('No inventory items found','Add a new item to get started'); return; }
  const isAdmin = currentUser.role === 'Admin';
  let html = `<table><thead><tr>
    <th><input type="checkbox" class="check-all" onchange="toggleAllItems(this)"/></th>
    <th>SKU</th><th>Item Name</th><th>Customer</th><th>Qty</th><th>Unit</th>
    <th>Min Level</th><th>Unit Cost</th><th>Location</th><th>Updated</th><th></th>
  </tr></thead><tbody>`;
  for (const i of rows) {
    const isLow = i.qty < i.min_level;
    const checked = selectedItems.has(i.id) ? 'checked' : '';
    html += `<tr>
      <td><input type="checkbox" value="${i.id}" ${checked} onchange="toggleItem(this,'${i.id}')"/></td>
      <td class="td-mono">${i.sku}</td>
      <td class="fw700">${i.name}</td>
      <td>${i.customer_name||'—'}</td>
      <td>${isLow ? `<span class="text-danger fw700">${fmt.num(i.qty)}</span> <span class="badge badge-red">Low</span>` : fmt.num(i.qty)}</td>
      <td>${i.unit||'PCS'}</td>
      <td>${fmt.num(i.min_level)}</td>
      <td class="nowrap">${fmt.sar(i.unit_cost)}</td>
      <td class="td-mono">${i.location||'—'}</td>
      <td class="text-muted">${fmt.date(i.updated)}</td>
      <td class="nowrap">
        <button class="btn btn-ghost btn-icon btn-sm" onclick='editInventoryItem(${JSON.stringify(i)})'>${icon.edit}</button>
        ${isAdmin?`<button class="btn btn-danger btn-icon btn-sm" onclick="deleteInventoryItem('${i.id}','${i.name}')">${icon.trash}</button>`:''}
      </td></tr>`;
  }
  html += `</tbody></table>`;
  document.getElementById('inv-table').innerHTML = html;
}

function toggleItem(cb, id) {
  if (cb.checked) selectedItems.add(id); else selectedItems.delete(id);
  updateBulkBar('inv-bulk-bar','inv-sel-count');
}
function toggleAllItems(cb) {
  document.querySelectorAll('#inv-table input[type=checkbox][value]').forEach(c => {
    c.checked = cb.checked;
    if (cb.checked) selectedItems.add(c.value); else selectedItems.delete(c.value);
  });
  updateBulkBar('inv-bulk-bar','inv-sel-count');
}
function clearSelection() { selectedItems.clear(); renderInvTable(); updateBulkBar('inv-bulk-bar','inv-sel-count'); }
function updateBulkBar(barId, countId) {
  const bar = document.getElementById(barId);
  const cnt = document.getElementById(countId);
  if (!bar||!cnt) return;
  if (selectedItems.size > 0) { bar.classList.add('show'); cnt.textContent = `${selectedItems.size} selected`; }
  else bar.classList.remove('show');
}

async function openAddInventory() {
  const customers = await API('/customers/names').catch(()=>[]);
  const custOpts = customers.map(c=>`<option>${c}</option>`).join('');
  openModal('Add Inventory Item', `
    <div class="field-row"><div class="field"><label>SKU</label><input id="i-sku" placeholder="ELC-001"/></div>
    <div class="field"><label>Item Name *</label><input id="i-name" placeholder="Motor Controller Unit"/></div></div>
    <div class="field"><label>Customer</label><select id="i-cust"><option value="">— Select Customer —</option>${custOpts}</select></div>
    <div class="field-row">
      <div class="field"><label>Quantity</label><input id="i-qty" type="number" value="0" min="0"/></div>
      <div class="field"><label>Unit</label><select id="i-unit"><option>PCS</option><option>KG</option><option>L</option><option>MTR</option><option>BOX</option><option>SET</option></select></div>
    </div>
    <div class="field-row">
      <div class="field"><label>Min Stock Level</label><input id="i-min" type="number" value="0" min="0"/></div>
      <div class="field"><label>Unit Cost (SAR)</label><input id="i-cost" type="number" step="0.01" value="0" min="0"/></div>
    </div>
    <div class="field"><label>Location</label><input id="i-loc" placeholder="A-01-1"/></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="saveInventoryItem()">Add Item</button>`);
}

async function saveInventoryItem() {
  const body = {
    sku: document.getElementById('i-sku').value.trim(),
    name: document.getElementById('i-name').value.trim(),
    customer_name: document.getElementById('i-cust').value,
    qty: +document.getElementById('i-qty').value,
    unit: document.getElementById('i-unit').value,
    min_level: +document.getElementById('i-min').value,
    unit_cost: +document.getElementById('i-cost').value,
    location: document.getElementById('i-loc').value.trim(),
  };
  if (!body.name) { toast('Item name is required','error'); return; }
  try {
    await API('/inventory', {method:'POST', body:JSON.stringify(body)});
    toast('Item added','success'); closeModal(); renderInventory();
  } catch(e) { toast(e.message,'error'); }
}

async function editInventoryItem(item) {
  const customers = await API('/customers/names').catch(()=>[]);
  const custOpts = customers.map(c=>`<option ${c===item.customer_name?'selected':''}>${c}</option>`).join('');
  openModal('Edit Inventory Item', `
    <div class="field-row">
      <div class="field"><label>SKU</label><input id="i-sku" value="${item.sku||''}" readonly style="background:var(--surface)"/></div>
      <div class="field"><label>Item Name *</label><input id="i-name" value="${item.name||''}"/></div>
    </div>
    <div class="field"><label>Customer</label><select id="i-cust"><option value="">— No Customer —</option>${custOpts}</select></div>
    <div class="field-row">
      <div class="field"><label>Quantity</label><input id="i-qty" type="number" value="${item.qty||0}" min="0"/></div>
      <div class="field"><label>Unit</label><select id="i-unit"><option ${item.unit==='PCS'?'selected':''}>PCS</option><option ${item.unit==='KG'?'selected':''}>KG</option><option ${item.unit==='L'?'selected':''}>L</option><option ${item.unit==='MTR'?'selected':''}>MTR</option><option ${item.unit==='BOX'?'selected':''}>BOX</option><option ${item.unit==='SET'?'selected':''}>SET</option></select></div>
    </div>
    <div class="field-row">
      <div class="field"><label>Min Stock Level</label><input id="i-min" type="number" value="${item.min_level||0}" min="0"/></div>
      <div class="field"><label>Unit Cost (SAR)</label><input id="i-cost" type="number" step="0.01" value="${item.unit_cost||0}" min="0"/></div>
    </div>
    <div class="field"><label>Location</label><input id="i-loc" value="${item.location||''}"/></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="updateInventoryItem('${item.id}')">Save Changes</button>`);
}

async function updateInventoryItem(id) {
  const body = {
    name: document.getElementById('i-name').value.trim(),
    customer_name: document.getElementById('i-cust').value,
    qty: +document.getElementById('i-qty').value,
    unit: document.getElementById('i-unit').value,
    min_level: +document.getElementById('i-min').value,
    unit_cost: +document.getElementById('i-cost').value,
    location: document.getElementById('i-loc').value.trim(),
  };
  try {
    await API(`/inventory/${id}`, {method:'PUT', body:JSON.stringify(body)});
    toast('Item updated','success'); closeModal(); renderInventory();
  } catch(e) { toast(e.message,'error'); }
}

async function deleteInventoryItem(id, name) {
  if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
  try {
    await API(`/inventory/${id}`, {method:'DELETE'});
    toast('Item deleted','success'); renderInventory();
  } catch(e) { toast(e.message,'error'); }
}

async function bulkEditSelected() {
  if (!selectedItems.size) { toast('Select items first','info'); return; }
  const customers = await API('/customers/names').catch(()=>[]);
  const custOpts = customers.map(c=>`<option>${c}</option>`).join('');
  openModal(`Bulk Edit ${selectedItems.size} Items`, `
    <p class="text-muted" style="margin-bottom:16px">Only filled fields will be applied to all selected items.</p>
    <div class="field"><label>Reassign Customer</label><select id="be-cust"><option value="">— Keep Existing —</option>${custOpts}</select></div>
    <div class="field-row">
      <div class="field"><label>Min Stock Level</label><input id="be-min" type="number" placeholder="Leave blank to skip"/></div>
      <div class="field"><label>Unit Cost (SAR)</label><input id="be-cost" type="number" step="0.01" placeholder="Leave blank to skip"/></div>
    </div>
    <div class="field-row">
      <div class="field"><label>Location</label><input id="be-loc" placeholder="Leave blank to skip"/></div>
      <div class="field"><label>Unit</label><select id="be-unit"><option value="">— Keep Existing —</option><option>PCS</option><option>KG</option><option>L</option><option>MTR</option><option>BOX</option><option>SET</option></select></div>
    </div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="saveBulkEdit()">Apply to ${selectedItems.size} Items</button>`);
}

async function saveBulkEdit() {
  const update = {};
  const cust = document.getElementById('be-cust').value;
  const min = document.getElementById('be-min').value;
  const cost = document.getElementById('be-cost').value;
  const loc = document.getElementById('be-loc').value;
  const unit = document.getElementById('be-unit').value;
  if (cust) update.customer_name = cust;
  if (min !== '') update.min_level = +min;
  if (cost !== '') update.unit_cost = +cost;
  if (loc) update.location = loc;
  if (unit) update.unit = unit;
  if (!Object.keys(update).length) { toast('No changes to apply','info'); return; }
  try {
    const r = await API('/inventory/bulk-update', {method:'POST', body:JSON.stringify({item_ids:[...selectedItems], update})});
    toast(`Updated ${r.updated} items${r.skipped?`, skipped ${r.skipped}`:''}`, 'success');
    closeModal(); clearSelection(); renderInventory();
  } catch(e) { toast(e.message,'error'); }
}

async function bulkDeleteSelected() {
  if (!selectedItems.size) { toast('Select items first','info'); return; }
  if (!confirm(`Delete ${selectedItems.size} items? This cannot be undone.`)) return;
  try {
    const r = await API('/inventory/bulk-delete', {method:'POST', body:JSON.stringify({item_ids:[...selectedItems]})});
    toast(`Deleted ${r.deleted} items`,'success'); clearSelection(); renderInventory();
  } catch(e) { toast(e.message,'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   STOCK IN/OUT
═══════════════════════════════════════════════════════════════════════════ */
"""
