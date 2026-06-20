"""Auth Users routes for the WMS backend."""

from wms_core import *

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.json or {}
    username = data.get("username", "").strip().lower()
    password = data.get("password", "")
    users = load_json(USERS_FILE, [])
    user = next((u for u in users if u["username"].lower() == username), None)
    if not user or user["password"] != hash_pw(password):
        log_activity(username or "unknown", "Login failed", "Auth", "Invalid credentials", status="error")
        return jsonify({"error": "Invalid username or password"}), 401
    if user["status"] != "Active":
        log_activity(username, "Login blocked", "Auth", "Account inactive", status="error")
        return jsonify({"error": "Account is inactive"}), 403
    user["last_login"] = now_str()
    save_json(USERS_FILE, users)
    token = str(uuid.uuid4())
    sessions = load_json(SESSIONS_FILE, {})
    sessions[token] = {
        "user_id": user["id"], "username": user["username"],
        "name": user["name"], "role": user["role"], "access": user["access"],
        "issued_at": now_str(),
        "expires_at": (datetime.datetime.now() + datetime.timedelta(seconds=SESSION_TIMEOUT_SECONDS)).isoformat(timespec="seconds")
    }
    save_json(SESSIONS_FILE, sessions)
    log_activity(user["username"], "Logged in", "Auth", f"Role: {user['role']}")
    return jsonify({
        "token": token,
        "expires_at": sessions[token]["expires_at"],
        "timeout_seconds": SESSION_TIMEOUT_SECONDS,
        "user": {"id": user["id"], "name": user["name"],
                 "username": user["username"], "role": user["role"],
                 "access": user["access"]}
    })

@app.route("/api/auth/logout", methods=["POST"])
@require_auth
def logout():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    sessions = load_json(SESSIONS_FILE, {})
    sessions.pop(token, None)
    save_json(SESSIONS_FILE, sessions)
    log_activity(request.current_user["username"], "Logged out", "Auth")
    return jsonify({"message": "Logged out"})

@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    return jsonify(request.current_user)

# ── Users ─────────────────────────────────────────────────────────────────────
@app.route("/api/users", methods=["GET"])
@require_admin
def get_users():
    users = load_json(USERS_FILE, [])
    return jsonify([{k: v for k, v in u.items() if k != "password"} for u in users])

@app.route("/api/users", methods=["POST"])
@require_admin
def create_user():
    data = request.json or {}
    users = load_json(USERS_FILE, [])
    if any(u["username"].lower() == data.get("username", "").lower() for u in users):
        return jsonify({"error": "Username already exists"}), 409
    new_user = {
        "id": str(uuid.uuid4()),
        "name": data.get("name", ""),
        "username": data.get("username", "").strip().lower(),
        "password": hash_pw(data.get("password", "password123")),
        "role": data.get("role", "Staff"),
        "access": data.get("access", ["Dashboard", "Customers"]),
        "status": "Active",
        "created": today_str(),
        "last_login": None
    }
    users.append(new_user)
    save_json(USERS_FILE, users)
    log_activity(request.current_user["username"], "Created user", "Users",
                 f"{new_user['name']} ({new_user['username']}) role:{new_user['role']}")
    return jsonify({k: v for k, v in new_user.items() if k != "password"}), 201

@app.route("/api/users/<uid>", methods=["PUT"])
@require_admin
def update_user(uid):
    data = request.json or {}
    users = load_json(USERS_FILE, [])
    user = next((u for u in users if u["id"] == uid), None)
    if not user:
        return jsonify({"error": "User not found"}), 404
    for field in ["name", "role", "access", "status"]:
        if field in data:
            user[field] = data[field]
    if "password" in data and data["password"]:
        user["password"] = hash_pw(data["password"])
    save_json(USERS_FILE, users)
    # Refresh active sessions for this user
    sessions = load_json(SESSIONS_FILE, {})
    for token, sess in sessions.items():
        if sess.get("user_id") == uid:
            sess["access"] = user["access"]
            sess["role"] = user["role"]
    save_json(SESSIONS_FILE, sessions)
    log_activity(request.current_user["username"], "Updated user", "Users",
                 f"{user['name']} ({user['username']}) — access updated")
    return jsonify({k: v for k, v in user.items() if k != "password"})

@app.route("/api/users/<uid>", methods=["DELETE"])
@require_admin
def delete_user(uid):
    users = load_json(USERS_FILE, [])
    target = next((u for u in users if u["id"] == uid), None)
    users = [u for u in users if u["id"] != uid]
    if target is None:
        return jsonify({"error": "User not found"}), 404
    save_json(USERS_FILE, users)
    log_activity(request.current_user["username"], "Deleted user", "Users",
                 f"{target['name']} ({target['username']})" if target else uid)
    return jsonify({"message": "User deleted"})



# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
<div id="app">
  <!-- Sidebar -->
  <aside class="sidebar">
    <div class="sidebar-header">
      <div class="sidebar-brand">
        <div class="brand-icon">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2">
            <path d="M4 7h16M4 12h16M4 17h10"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>
          </svg>
        </div>
        <div class="sidebar-brand-text">
          <h2>MS Warehouse</h2>
          <p>WMS v2.0</p>
        </div>
      </div>
    </div>
    <div class="sidebar-user">
      <div class="user-avatar" id="user-avatar">MS</div>
      <div class="user-info">
        <div class="name" id="user-name">Mohammad Siddiq</div>
        <div class="role" id="user-role">Admin</div>
      </div>
    </div>
    <nav class="sidebar-nav" id="sidebar-nav">
      <!-- Filled by JS -->
    </nav>
    <div class="sidebar-footer">
      <button class="btn-logout" id="logout-btn">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        Sign out
      </button>
    </div>
  </aside>

  <!-- Main -->
  <main class="main-content" id="main-content">
    <!-- Pages injected here -->
  </main>
</div>

<!-- Toast -->
<div id="toast-container"></div>

<!-- Modals -->
<div class="modal-overlay" id="modal-overlay">
  <div class="modal" id="modal-box">
    <div class="modal-header">
      <h3 id="modal-title"></h3>
      <button class="modal-close" id="modal-close-btn">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
    <div class="modal-body" id="modal-body"></div>
    <div class="modal-footer" id="modal-footer"></div>
  </div>
</div>

<script>
/* ═══════════════════════════════════════════════════════════════════════════
   CONFIG
═══════════════════════════════════════════════════════════════════════════ */
const API = (path, opts={}) => {
  const token = localStorage.getItem('wms_token');
  return fetch(`/api${path}`, {
    headers: { 'Content-Type':'application/json', ...(token ? {'Authorization':`Bearer ${token}`} : {}), ...opts.headers },
    ...opts
  }).then(async r => {
    const data = await r.json().catch(()=>({}));
    if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
    return data;
  });
};

/* ═══════════════════════════════════════════════════════════════════════════
   STATE
═══════════════════════════════════════════════════════════════════════════ */
let currentUser = null;
let currentPage = 'dashboard';
let selectedItems = new Set();

/* ═══════════════════════════════════════════════════════════════════════════
   TOAST
═══════════════════════════════════════════════════════════════════════════ */

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

function launchApp() {
  document.getElementById('login-screen').style.display='none';
  document.getElementById('app').classList.add('active');
  buildSidebar();
  navigate('dashboard');
}
"""
