"""Settings Logs routes for the WMS backend."""

from wms_core import *

@app.route("/api/settings", methods=["GET"])
@require_auth
def get_settings():
    return jsonify(load_json(SETTINGS_FILE, default_settings()))

@app.route("/api/settings", methods=["PUT"])
@require_admin
def update_settings():
    data = request.json or {}
    settings = load_json(SETTINGS_FILE, default_settings())
    allowed = ["warehouse_name", "location", "manager", "phone",
               "currency", "date_format", "retention_days", "vat_percent"]
    changed = []
    for k in allowed:
        if k in data:
            settings[k] = data[k]
            changed.append(k)
    save_json(SETTINGS_FILE, settings)
    log_activity(request.current_user["username"], "Updated settings", "Settings",
                 f"Changed: {', '.join(changed)}" if changed else "No fields changed")
    return jsonify(settings)

# ── Activity Log ───────────────────────────────────────────────────────────────
@app.route("/api/logs", methods=["GET"])
@require_auth
def get_logs():
    logs = load_json(LOGS_FILE, [])
    if request.current_user.get("role") != "Admin":
        logs = [l for l in logs if l["username"] == request.current_user["username"]]
    category = request.args.get("category", "")
    username = request.args.get("username", "")
    q = request.args.get("q", "").lower()
    if category:
        logs = [l for l in logs if l["category"] == category]
    if username and request.current_user.get("role") == "Admin":
        logs = [l for l in logs if l["username"] == username]
    if q:
        logs = [l for l in logs if q in l.get("action", "").lower() or
                q in l.get("details", "").lower()]
    limit = int(request.args.get("limit", 200))
    return jsonify(logs[::-1][:limit])

@app.route("/api/logs/categories", methods=["GET"])
@require_auth
def get_log_categories():
    logs = load_json(LOGS_FILE, [])
    if request.current_user.get("role") != "Admin":
        logs = [l for l in logs if l["username"] == request.current_user["username"]]
    return jsonify(sorted(set(l["category"] for l in logs)))

@app.route("/api/admin/clear-stock-data", methods=["POST"])
@require_admin
def clear_stock_data():
    """Clear all stored inventory items and stock movement transactions."""
    save_json(INVENTORY_FILE, [])
    save_json(TRANSACTIONS_FILE, [])
    log_activity(request.current_user["username"], "Cleared stock data", "Admin",
                 "All inventory and stock transactions were deleted", status="warning")
    return jsonify({"message": "Inventory and stock transactions cleared"})

@app.route("/api/admin/clear-billing-data", methods=["POST"])
@require_admin
def clear_billing_data():
    """Clear all stored billing records."""
    save_json(BILLS_FILE, [])
    log_activity(request.current_user["username"], "Cleared billing data", "Admin",
                 "All billing records were deleted", status="warning")
    return jsonify({"message": "Billing records cleared"})

# ── File Upload (Excel Import) ─────────────────────────────────────────────────


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'reports',    label:'Reports',      icon:'reports',    module:'Reports' },
  { id:'actlog',     label:'Activity Log', icon:'actlog',     module:'Activity Log' },
  { id:'templates',  label:'Templates',    icon:'templates',  module:'Templates', adminOnly:true },
  { id:'users',      label:'Users',        icon:'users',      module:'Users',      adminOnly:true },
  { id:'export',     label:'Export',       icon:'export',     module:'Export' },
];


async function renderActivityLog() {
  setMain(`
    <div class="page-header">
      <div><h1>Activity Log</h1><div class="subtitle">Full audit trail of all warehouse actions</div></div>
    </div>
    <div class="page-body">
      <div class="toolbar">
        <div class="search-box"><span class="search-icon">${icon.search}</span><input id="log-search" placeholder="Search logs…" oninput="filterLogs()"/></div>
        <select class="filter-select" id="log-cat" onchange="filterLogs()"><option value="">All Categories</option>
          ${['Auth','Inventory','Stock In/Out','Billing','Customers','Users','Templates','Files','Export'].map(c=>`<option>${c}</option>`).join('')}
        </select>
      </div>
      <div class="card" id="log-card">${loadingHtml()}</div>
    </div>`);
  try {
    const logs = await API('/logs?limit=200');
    renderLogTable(logs);
  } catch(e) { document.getElementById('log-card').innerHTML=`<p class="text-danger" style="padding:20px">${e.message}</p>`; }
}

let logData = [];
function renderLogTable(data) {
  logData = data;
  filterLogs();
}
function filterLogs() {
  const q = (document.getElementById('log-search')||{}).value?.toLowerCase()||'';
  const cat = (document.getElementById('log-cat')||{}).value||'';
  let rows = logData.filter(l =>
    (!q || l.action.toLowerCase().includes(q) || l.username.includes(q) || (l.details||'').toLowerCase().includes(q)) &&
    (!cat || l.category===cat)
  );
  if (!rows.length) { document.getElementById('log-card').innerHTML=emptyHtml('No log entries found'); return; }
  let html = `<div class="table-wrap"><table><thead><tr><th>Time</th><th>User</th><th>Category</th><th>Action</th><th>Details</th><th>Status</th></tr></thead><tbody>`;
  for (const l of rows) {
    html += `<tr>
      <td class="text-muted nowrap">${fmt.dt(l.datetime)}</td>
      <td class="fw700">${l.username}</td>
      <td>${badge(l.category,{Auth:'badge-blue',Inventory:'badge-blue','Stock In/Out':'badge-green',Billing:'badge-amber',Customers:'badge-blue',Users:'badge-gray',Templates:'badge-gray'})}</td>
      <td>${l.action}</td>
      <td class="text-muted">${l.details||'—'}</td>
      <td>${badge(l.status||'success',{success:'badge-green',error:'badge-red',warning:'badge-amber'})}</td>
    </tr>`;
  }
  html += `</tbody></table></div>`;
  document.getElementById('log-card').innerHTML = html;
}

/* ═══════════════════════════════════════════════════════════════════════════
   USERS (Admin only)
═══════════════════════════════════════════════════════════════════════════ */
const ALL_MODULES = ['Dashboard','Inventory','Stock In/Out','Billing','Reports','Activity Log','Customers','Export'];

async function renderUsers() {
  setMain(`
    <div class="page-header">
      <div><h1>Users</h1><div class="subtitle">Manage team access and roles</div></div>
      <div class="header-actions">
        <button class="btn btn-accent btn-sm" onclick="openAddUser()">${icon.plus} Add User</button>
      </div>
    </div>
    <div class="page-body" id="users-body">${loadingHtml()}</div>`);
  try {
    const users = await API('/users');
    let html = `<div class="card"><div class="table-wrap"><table>
      <thead><tr><th>Name</th><th>Username</th><th>Role</th><th>Status</th><th>Access</th><th>Last Login</th><th></th></tr></thead><tbody>`;
    for (const u of users) {
      html += `<tr>
        <td class="fw700">${u.name}</td>
        <td class="td-mono">@${u.username}</td>
        <td>${badge(u.role,{Admin:'badge-blue',Staff:'badge-gray'})}</td>
        <td>${badge(u.status,{Active:'badge-green',Inactive:'badge-red'})}</td>
        <td style="max-width:240px;font-size:11px;color:var(--ink-3)">${(u.access||[]).join(', ')||'—'}</td>
        <td class="text-muted">${fmt.dt(u.last_login)||'Never'}</td>
        <td class="nowrap">
          <button class="btn btn-ghost btn-icon btn-sm" onclick='openEditUser(${JSON.stringify(u)})'>${icon.edit}</button>
          ${u.username!=='admin'?`<button class="btn btn-danger btn-icon btn-sm" onclick="deleteUser('${u.id}','${u.name}')">${icon.trash}</button>`:''}
        </td></tr>`;
    }
    html += `</tbody></table></div></div>`;
    document.getElementById('users-body').innerHTML = html;
  } catch(e) { document.getElementById('users-body').innerHTML=`<p class="text-danger">${e.message}</p>`; }
}

function moduleCheckboxes(selected=[]) {
  return ALL_MODULES.map(m=>`
    <label style="display:flex;align-items:center;gap:7px;font-size:13px;margin-bottom:6px;cursor:pointer">
      <input type="checkbox" name="mod" value="${m}" ${selected.includes(m)?'checked':''}/>
      ${m}
    </label>`).join('');
}

async function openAddUser() {
  openModal('Add User', `
    <div class="field-row">
      <div class="field"><label>Full Name *</label><input id="u-name" placeholder="Ahmed Al-Rashid"/></div>
      <div class="field"><label>Username *</label><input id="u-user" placeholder="ahmed"/></div>
    </div>
    <div class="field-row">
      <div class="field"><label>Password *</label><input id="u-pass" type="password"/></div>
      <div class="field"><label>Role</label><select id="u-role"><option>Staff</option><option>Admin</option></select></div>
    </div>
    <div class="field"><label>Module Access</label>${moduleCheckboxes(['Dashboard','Customers'])}</div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="saveUser()">Create User</button>`);
}

async function saveUser() {
  const access = [...document.querySelectorAll('input[name=mod]:checked')].map(c=>c.value);
  const body = {
    name: document.getElementById('u-name').value.trim(),
    username: document.getElementById('u-user').value.trim(),
    password: document.getElementById('u-pass').value,
    role: document.getElementById('u-role').value,
    access,
  };
  if (!body.name||!body.username||!body.password) { toast('Name, username and password are required','error'); return; }
  try {
    await API('/users', {method:'POST', body:JSON.stringify(body)});
    toast('User created','success'); closeModal(); renderUsers();
  } catch(e) { toast(e.message,'error'); }
}

async function openEditUser(u) {
  openModal(`Edit User — ${u.name}`, `
    <div class="field-row">
      <div class="field"><label>Full Name</label><input id="u-name" value="${u.name}"/></div>
      <div class="field"><label>Role</label><select id="u-role"><option ${u.role==='Staff'?'selected':''}>Staff</option><option ${u.role==='Admin'?'selected':''}>Admin</option></select></div>
    </div>
    <div class="field-row">
      <div class="field"><label>Status</label><select id="u-status"><option ${u.status==='Active'?'selected':''}>Active</option><option ${u.status==='Inactive'?'selected':''}>Inactive</option></select></div>
      <div class="field"><label>New Password</label><input id="u-pass" type="password" placeholder="Leave blank to keep"/></div>
    </div>
    <div class="field"><label>Module Access</label>${moduleCheckboxes(u.access||[])}</div>`,
    `<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>
     <button class="btn btn-accent" onclick="updateUser('${u.id}')">Save Changes</button>`);
}

async function updateUser(id) {
  const access = [...document.querySelectorAll('input[name=mod]:checked')].map(c=>c.value);
  const body = {
    name: document.getElementById('u-name').value.trim(),
    role: document.getElementById('u-role').value,
    status: document.getElementById('u-status').value,
    access,
  };
  const pass = document.getElementById('u-pass').value;
  if (pass) body.password = pass;
  try {
    await API(`/users/${id}`, {method:'PUT', body:JSON.stringify(body)});
    toast('User updated','success'); closeModal(); renderUsers();
  } catch(e) { toast(e.message,'error'); }
}

async function deleteUser(id, name) {
  if (!confirm(`Delete user "${name}"?`)) return;
  try {
    await API(`/users/${id}`, {method:'DELETE'});
    toast('User deleted','success'); renderUsers();
  } catch(e) { toast(e.message,'error'); }
}

/* ═══════════════════════════════════════════════════════════════════════════
   TEMPLATES (Admin only)
═══════════════════════════════════════════════════════════════════════════ */
"""
