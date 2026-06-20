"""Customers routes for the WMS backend."""

from wms_core import *

# Customers are stored in customers.json. Each customer has an assigned_to (username).
# Admin sees all customers with user column.
# Staff sees only their assigned customers.

@app.route("/api/customers", methods=["GET"])
@require_auth
def get_customers():
    cu = request.current_user
    customers = load_json(CUSTOMERS_FILE, [])
    if cu["role"] != "Admin":
        # Users see only their own customers
        customers = [c for c in customers if c.get("assigned_to") == cu["username"]]
    q = request.args.get("q", "").lower()
    if q:
        customers = [c for c in customers if q in c["name"].lower()]
    assigned = request.args.get("assigned_to", "")
    if assigned and cu["role"] == "Admin":
        customers = [c for c in customers if c.get("assigned_to") == assigned]
    return jsonify(sorted(customers, key=lambda c: c["name"].lower()))

@app.route("/api/customers/names", methods=["GET"])
@require_auth
def get_customer_names():
    """Lightweight name list for dropdowns (e.g. Stock In/Out, Inventory forms).
    Same scoping as GET /api/customers: admin sees all, others see only their own."""
    cu = request.current_user
    customers = get_user_customers(cu)
    names = sorted({c["name"] for c in customers}, key=str.lower)
    return jsonify(names)

@app.route("/api/customers", methods=["POST"])
@require_auth
def create_customer():
    """Every user can onboard customers. Non-admins are auto-assigned to themselves."""
    cu = request.current_user
    data = request.json or {}
    customers = load_json(CUSTOMERS_FILE, [])
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Customer name is required"}), 400
    # Admins can assign to any user; others get auto-assigned
    assigned_to = data.get("assigned_to", cu["username"])
    if cu["role"] != "Admin":
        assigned_to = cu["username"]
    new_customer = {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": data.get("phone", ""),
        "email": data.get("email", ""),
        "address": data.get("address", ""),
        "assigned_to": assigned_to,
        "created_by": cu["username"],
        "created_at": now_str(),
        "status": data.get("status", "Active"),
        "notes": data.get("notes", "")
    }
    customers.append(new_customer)
    save_json(CUSTOMERS_FILE, customers)
    log_activity(cu["username"], "Customer onboarded", "Customers",
                 f"{name} assigned to {assigned_to}")
    return jsonify(new_customer), 201

@app.route("/api/customers/<cid>", methods=["PUT"])
@require_auth
def update_customer(cid):
    cu = request.current_user
    data = request.json or {}
    customers = load_json(CUSTOMERS_FILE, [])
    customer = next((c for c in customers if c["id"] == cid), None)
    if not customer:
        return jsonify({"error": "Customer not found"}), 404
    # Non-admins can only edit their own customers
    if cu["role"] != "Admin" and customer.get("assigned_to") != cu["username"]:
        return jsonify({"error": "Access denied"}), 403
    for field in ["name", "phone", "email", "address", "status", "notes"]:
        if field in data:
            customer[field] = data[field]
    # Only admin can reassign
    if cu["role"] == "Admin" and "assigned_to" in data:
        customer["assigned_to"] = data["assigned_to"]
    save_json(CUSTOMERS_FILE, customers)
    log_activity(cu["username"], "Updated customer", "Customers", customer["name"])
    return jsonify(customer)

@app.route("/api/customers/<cid>", methods=["DELETE"])
@require_auth
def delete_customer(cid):
    cu = request.current_user
    customers = load_json(CUSTOMERS_FILE, [])
    customer = next((c for c in customers if c["id"] == cid), None)
    if not customer:
        return jsonify({"error": "Customer not found"}), 404
    if cu["role"] != "Admin" and customer.get("assigned_to") != cu["username"]:
        return jsonify({"error": "Access denied"}), 403
    customers = [c for c in customers if c["id"] != cid]
    save_json(CUSTOMERS_FILE, customers)
    log_activity(cu["username"], "Deleted customer", "Customers", customer["name"])
    return jsonify({"message": "Customer deleted"})

@app.route("/api/customers/admin-view", methods=["GET"])
@require_admin
def customers_admin_view():
    """
    Admin view: returns customers with two display rows per customer:
      row 1 = customer name, row 2 = assigned username
    Also includes full user info for each assigned user.
    """
    customers = load_json(CUSTOMERS_FILE, [])
    users = load_json(USERS_FILE, [])
    user_map = {u["username"]: u["name"] for u in users}
    result = []
    for c in sorted(customers, key=lambda x: x["name"].lower()):
        result.append({
            **c,
            "display_row_1": c["name"],                             # customer name row
            "display_row_2": user_map.get(c.get("assigned_to"), c.get("assigned_to", "—")),  # user name row
            "assigned_user_fullname": user_map.get(c.get("assigned_to"), "—")
        })
    return jsonify(result)

# ── Inventory (Customer-centric) ──────────────────────────────────────────────
# Inventory items are now linked to a customer. Browsing is by customer.


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'customers',  label:'Customers',    icon:'customers',  module:'Customers' },
  { id:'reports',    label:'Reports',      icon:'reports',    module:'Reports' },

async function renderCustomers() {
  setMain(`
    <div class="page-header">
      <div><h1>Customers</h1><div class="subtitle">Manage customer accounts</div></div>
      <div class="header-actions">
        <button class="btn btn-ghost btn-sm" onclick="renderCustomers()">${icon.refresh} Refresh</button>
        <button class="btn btn-accent btn-sm" onclick="openAddCustomer()">${icon.plus} Onboard Customer</button>
      </div>
    </div>
    <div class="page-body">
      <div class="toolbar">
        <div class="search-box"><span class="search-icon">${icon.search}</span><input id="cust-search" placeholder="Search customers…" oninput="filterCustomers()"/></div>
        ${currentUser.role==='Admin'?`<select class="filter-select" id="cust-user-filter" onchange="filterCustomers()"><option value="">All Users</option></select>`:''}
      </div>
      <div class="card"><div class="table-wrap" id="cust-table">${loadingHtml()}</div></div>
    </div>`);

  try {
    let customers;
    if (currentUser.role==='Admin') {
      customers = await API('/customers/admin-view');
      const users = [...new Set(customers.map(c=>c.assigned_to||'—'))];
      const sel = document.getElementById('cust-user-filter');
      if (sel) users.forEach(u => { const o=document.createElement('option');o.value=u;o.textContent=u;sel.appendChild(o); });
    } else {
      customers = await API('/customers');
    }
    renderCustTable(customers);
  } catch(e) { document.getElementById('cust-table').innerHTML=`<p class="text-danger" style="padding:20px">${e.message}</p>`; }
}

let custData = [];
function renderCustTable(data) {
  custData = data;
  filterCustomers();
}
function filterCustomers() {
  const q = (document.getElementById('cust-search')||{}).value?.toLowerCase()||'';
  const u = (document.getElementById('cust-user-filter')||{}).value||'';
  let rows = custData.filter(c =>
    (!q || c.name.toLowerCase().includes(q)) &&
    (!u || c.assigned_to===u)
  );
  if (!rows.length) { document.getElementById('cust-table').innerHTML=emptyHtml('No customers found','Onboard your first customer'); return; }
  const isAdmin = currentUser.role==='Admin';
  let html = `<table><thead><tr><th>Customer</th>${isAdmin?'<th>Assigned To</th>':''}<th>Status</th><th>Phone</th><th>Email</th><th>Created</th><th></th></tr></thead><tbody>`;
  for (const c of rows) {
    html += `<tr>
      <td><div class="row-name">${c.name}</div>${c.created_by?`<div class="row-user">Added by ${c.created_by}</div>`:''}</td>
      ${isAdmin?`<td><div class="row-name">${c.assigned_user_fullname||c.assigned_to||'—'}</div><div class="row-user">@${c.assigned_to||'—'}</div></td>`:''}
      <td>${badge(c.status||'Active',{Active:'badge-green',Inactive:'badge-gray'})}</td>
      <td>${c.phone||'—'}</td>
      <td>${c.email||'—'}</td>
      <td class="text-muted">${fmt.date(c.created_at)}</td>
      <td class="nowrap">
        <button class="btn btn-ghost btn-icon btn-sm" onclick='editCustomer(${JSON.stringify(c)})'>${icon.edit}</button>
        <button class="btn btn-danger btn-icon btn-sm" onclick="deleteCustomer('${c.id}','${c.name}')">${icon.trash}</button>
      </td></tr>`;
  }
  html += `</tbody></table>`;
  document.getElementById('cust-table').innerHTML = html;
}

async function openAddCustomer() {
  const isAdmin = currentUser.role==='Admin';
  let userOpts = '';
  if (isAdmin) {
    const users = await API('/users').catch(()=>[]);
    userOpts = `<div class="field"><label>Assign To</label><select id="c-assign">
      ${users.map(u=>`<option value="${u.username}">${u.name} (@${u.username})</option>`).join('')}
    </select></div>`;
  }
  openModal('Onboard New Customer', `
    <div class="field"><label>Customer Name *</label><input id="c-name" placeholder="Al-Noor Supplies"/></div>
    <div class="field-row">
      <div class="field"><label>Phone</label><input id="c-phone" placeholder="+966 5X XXX XXXX"/></div>
      <div class="field"><label>Email</label><input id="c-email" type="email" placeholder="contact@company.com"/></div>
    </div>
    <div class="field"><label>Address</label><input id="c-addr" placeholder="Riyadh, Saudi Arabia"/></div>
    ${userOpts}
    <div class="field"><label>Notes</label><textarea id="c-notes" rows="2"></textarea></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="saveCustomer()">Onboard</button>`);
}

async function saveCustomer() {
  const body = {
    name: document.getElementById('c-name').value.trim(),
    phone: document.getElementById('c-phone').value,
    email: document.getElementById('c-email').value,
    address: document.getElementById('c-addr').value,
    notes: document.getElementById('c-notes').value,
  };
  const assign = document.getElementById('c-assign');
  if (assign) body.assigned_to = assign.value;
  if (!body.name) { toast('Customer name is required','error'); return; }
  try {
    await API('/customers', {method:'POST', body:JSON.stringify(body)});
    toast('Customer onboarded','success'); closeModal(); renderCustomers();
  } catch(e) { toast(e.message,'error'); }
}

async function editCustomer(c) {
  const isAdmin = currentUser.role==='Admin';
  let userOpts = '';
  if (isAdmin) {
    const users = await API('/users').catch(()=>[]);
    userOpts = `<div class="field"><label>Assign To</label><select id="c-assign">
      ${users.map(u=>`<option value="${u.username}" ${u.username===c.assigned_to?'selected':''}>${u.name} (@${u.username})</option>`).join('')}
    </select></div>`;
  }
  openModal('Edit Customer', `
    <div class="field"><label>Customer Name *</label><input id="c-name" value="${c.name}"/></div>
    <div class="field-row">
      <div class="field"><label>Phone</label><input id="c-phone" value="${c.phone||''}"/></div>
      <div class="field"><label>Email</label><input id="c-email" type="email" value="${c.email||''}"/></div>
    </div>
    <div class="field"><label>Address</label><input id="c-addr" value="${c.address||''}"/></div>
    <div class="field"><label>Status</label><select id="c-status">
      <option ${c.status==='Active'?'selected':''}>Active</option>
      <option ${c.status==='Inactive'?'selected':''}>Inactive</option>
    </select></div>
    ${userOpts}
    <div class="field"><label>Notes</label><textarea id="c-notes" rows="2">${c.notes||''}</textarea></div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="updateCustomer('${c.id}')">Save Changes</button>`);
}

async function updateCustomer(id) {
  const body = {
    name: document.getElementById('c-name').value.trim(),
    phone: document.getElementById('c-phone').value,
    email: document.getElementById('c-email').value,
    address: document.getElementById('c-addr').value,
    status: document.getElementById('c-status').value,
    notes: document.getElementById('c-notes').value,
  };
  const assign = document.getElementById('c-assign');
  if (assign) body.assigned_to = assign.value;
  try {
    await API(`/customers/${id}`, {method:'PUT', body:JSON.stringify(body)});
    toast('Customer updated','success'); closeModal(); renderCustomers();
  } catch(e) { toast(e.message,'error'); }
}

async function deleteCustomer(id, name) {
  if (!confirm(`Remove customer "${name}"?`)) return;
  try {
    await API(`/customers/${id}`, {method:'DELETE'});
    toast('Customer removed','success'); renderCustomers();
  } catch(e) { toast(e.message,'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   ACTIVITY LOG
═══════════════════════════════════════════════════════════════════════════ */
"""
