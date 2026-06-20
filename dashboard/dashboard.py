"""Dashboard routes for the WMS backend."""

from wms_core import *

@app.route("/api/dashboard", methods=["GET"])
@require_auth
def dashboard():
    cu = request.current_user
    is_admin = cu["role"] == "Admin"
    all_txns  = load_json(TRANSACTIONS_FILE, [])
    all_bills = load_json(BILLS_FILE, [])
    all_inv   = load_json(INVENTORY_FILE, [])
    customers = load_json(CUSTOMERS_FILE, [])
    today = today_str()

    if is_admin:
        # Admin sees global summary + per-user breakdown
        my_txns  = all_txns
        my_bills = all_bills
        my_inv   = all_inv
        my_customers = customers

        # Per-user summaries
        users = load_json(USERS_FILE, [])
        user_summaries = []
        for u in users:
            uname = u["username"]
            u_txns  = [t for t in all_txns  if t.get("by") == uname]
            u_bills = [b for b in all_bills if b.get("created_by") == uname]
            u_cust  = [c for c in customers if c.get("assigned_to") == uname]
            u_inv   = [i for i in all_inv   if i.get("created_by") == uname]
            today_u = [t for t in u_txns if t.get("date", t["datetime"][:10]) == today]
            user_summaries.append({
                "username": uname,
                "name": u["name"],
                "role": u["role"],
                "transactions": len(u_txns),
                "bills": len(u_bills),
                "customers": len(u_cust),
                "inventory_items": len(u_inv),
                "stock_in_today": sum(t["qty"] for t in today_u if t["type"] == "IN"),
                "stock_out_today": sum(t["qty"] for t in today_u if t["type"] == "OUT"),
            })
    else:
        # Regular user sees only their own data
        my_txns  = [t for t in all_txns  if t.get("by") == cu["username"]]
        my_bills = [b for b in all_bills if b.get("created_by") == cu["username"]]
        my_customers = [c for c in customers if c.get("assigned_to") == cu["username"]]
        my_inv   = [i for i in all_inv   if
                    i.get("created_by") == cu["username"] or
                    i.get("customer_name") in {c["name"] for c in my_customers}]
        user_summaries = []

    today_txns = [t for t in my_txns if t.get("date", t["datetime"][:10]) == today]

    # Customer stats
    cust_names = sorted({c["name"] for c in my_customers})

    # Customer-wise inventory breakdown
    by_customer = {}
    for i in my_inv:
        c = i.get("customer_name", "Unknown")
        if c not in by_customer:
            by_customer[c] = {"customer": c, "sku_count": 0, "total_value": 0.0, "total_qty": 0}
        by_customer[c]["sku_count"] += 1
        by_customer[c]["total_qty"] += i.get("qty", 0)
        by_customer[c]["total_value"] += i.get("qty", 0) * i.get("unit_cost", 0)

    # Admin customers panel with name + username rows
    admin_customers_panel = []
    if is_admin:
        users_list = load_json(USERS_FILE, [])
        user_map = {u["username"]: u["name"] for u in users_list}
        for c in sorted(customers, key=lambda x: x["name"].lower()):
            admin_customers_panel.append({
                "customer_name": c["name"],         # row 1: customer name
                "assigned_username": c.get("assigned_to", "—"),  # row 2: username
                "assigned_user_fullname": user_map.get(c.get("assigned_to"), "—"),
                "status": c.get("status", "Active")
            })

    return jsonify({
        "stats": {
            "total_items": len(my_inv),
            "total_value": round(sum(i["qty"] * i.get("unit_cost", 0) for i in my_inv), 2),
            "stock_in_today": sum(t["qty"] for t in today_txns if t["type"] == "IN"),
            "stock_out_today": sum(t["qty"] for t in today_txns if t["type"] == "OUT"),
            "pending_bills": len([b for b in my_bills if b["status"] == "Pending"]),
            "pending_value": sum(b["amount"] for b in my_bills if b["status"] == "Pending"),
            "total_customers": len(my_customers),
            "low_stock_count": len([i for i in my_inv if i["qty"] < i.get("min_level", 0)]),
        },
        "low_stock": [i for i in my_inv if i["qty"] < i.get("min_level", 0)],
        "by_customer": list(by_customer.values()),
        "customers": cust_names,
        "admin_customers_panel": admin_customers_panel,   # admin only (name row + user row)
        "user_summaries": user_summaries,                 # admin only
        "recent_activity": my_txns[-8:][::-1],
        "is_admin": is_admin
    })


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'inventory',  label:'Inventory',    icon:'inventory',  module:'Inventory' },
  { id:'stockio',    label:'Stock In/Out', icon:'stockio',    module:'Stock In/Out' },
  { id:'billing',    label:'Billing',      icon:'billing',    module:'Billing' },
  { id:'customers',  label:'Customers',    icon:'customers',  module:'Customers' },
  { id:'reports',    label:'Reports',      icon:'reports',    module:'Reports' },
  { id:'actlog',     label:'Activity Log', icon:'actlog',     module:'Activity Log' },

function renderPage(page) {
  selectedItems.clear();
  const pages = {
    dashboard:  renderDashboard,
    inventory:  renderInventory,
    stockio:    renderStockIO,
    billing:    renderBilling,
    customers:  renderCustomers,
    reports:    renderReports,
    actlog:     renderActivityLog,
    templates:  renderTemplates,
    users:      renderUsers,
    export:     renderExport,
  };
  if (pages[page]) pages[page]();
  else setMain(`<div class="page-body"><p>Page not found.</p></div>`);
}

/* ═══════════════════════════════════════════════════════════════════════════
   DASHBOARD
═══════════════════════════════════════════════════════════════════════════ */
async function renderDashboard() {
  setMain(`<div class="page-header"><div><h1>Dashboard</h1><div class="subtitle">Overview of your warehouse operations</div></div></div><div class="page-body">${loadingHtml()}</div>`);
  try {
    const d = await API('/dashboard');
    const s = d.stats;
    const isAdmin = d.is_admin;

    let html = `
    <div class="stat-grid">
      <div class="stat-card"><div class="stat-icon blue">${icon.inventory}</div><div class="stat-label">Total SKUs</div><div class="stat-value">${fmt.num(s.total_items)}</div><div class="stat-sub">Inventory items</div></div>
      <div class="stat-card"><div class="stat-icon green">${icon.reports}</div><div class="stat-label">Stock Value</div><div class="stat-value" style="font-size:20px">${fmt.sar(s.total_value)}</div><div class="stat-sub">Total inventory value</div></div>
      <div class="stat-card"><div class="stat-icon green">${icon.stockio}</div><div class="stat-label">Stock In Today</div><div class="stat-value">${fmt.num(s.stock_in_today)}</div><div class="stat-sub">Units received</div></div>
      <div class="stat-card"><div class="stat-icon amber">${icon.stockio}</div><div class="stat-label">Stock Out Today</div><div class="stat-value">${fmt.num(s.stock_out_today)}</div><div class="stat-sub">Units dispatched</div></div>
      <div class="stat-card"><div class="stat-icon blue">${icon.customers}</div><div class="stat-label">Customers</div><div class="stat-value">${fmt.num(s.total_customers)}</div><div class="stat-sub">Active accounts</div></div>
      ${s.low_stock_count > 0 ? `<div class="stat-card"><div class="stat-icon red">${icon.warning}</div><div class="stat-label">Low Stock</div><div class="stat-value text-danger">${fmt.num(s.low_stock_count)}</div><div class="stat-sub">Items below minimum</div></div>` : ''}
      <div class="stat-card"><div class="stat-icon amber">${icon.billing}</div><div class="stat-label">Pending Bills</div><div class="stat-value">${fmt.num(s.pending_bills)}</div><div class="stat-sub">${fmt.sar(s.pending_value)}</div></div>
    </div>`;

    html += `<div class="dash-grid">
      <div class="dash-col">`;

    // Customer breakdown
    if (d.by_customer && d.by_customer.length) {
      html += `<div class="card"><div class="card-header"><h3>Inventory by Customer</h3></div><div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>Customer</th><th>SKUs</th><th>Total Qty</th><th>Value</th></tr></thead><tbody>`;
      for (const c of d.by_customer) {
        html += `<tr><td class="fw700">${c.customer}</td><td>${fmt.num(c.sku_count)}</td><td>${fmt.num(c.total_qty)}</td><td class="nowrap">${fmt.sar(c.total_value)}</td></tr>`;
      }
      html += `</tbody></table></div></div></div>`;
    }

    // Low stock
    if (d.low_stock && d.low_stock.length) {
      html += `<div class="card"><div class="card-header"><h3 style="color:var(--red)">${icon.warning} Low Stock Alerts</h3></div><div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>SKU</th><th>Item</th><th>Customer</th><th>Qty</th><th>Min</th></tr></thead><tbody>`;
      for (const i of d.low_stock) {
        const pct = i.min_level > 0 ? Math.min(100, (i.qty / i.min_level) * 100) : 0;
        html += `<tr>
          <td class="td-mono">${i.sku}</td><td>${i.name}</td><td>${i.customer_name||'—'}</td>
          <td><span class="text-danger fw700">${fmt.num(i.qty)}</span>
            <div class="stock-bar"><div class="stock-bar-fill fill-low" style="width:${pct}%"></div></div></td>
          <td>${fmt.num(i.min_level)}</td></tr>`;
      }
      html += `</tbody></table></div></div></div>`;
    }

    html += `</div><div class="dash-col">`;

    // Recent activity
    html += `<div class="card"><div class="card-header"><h3>Recent Activity</h3></div><div class="card-body"><div class="log-list">`;
    if (d.recent_activity && d.recent_activity.length) {
      for (const t of d.recent_activity) {
        const isIN = t.type === 'IN';
        html += `<div class="log-item">
          <div class="log-dot"></div>
          <div><div class="log-action">${isIN ? '▲' : '▼'} ${t.name||t.sku}</div>
          <div class="log-meta">${t.customer_name ? t.customer_name+' · ' : ''}${fmt.num(t.qty)} units · ${fmt.date(t.date)} · ${t.by}</div></div>
          <span class="badge ${isIN ? 'badge-green':'badge-amber'}" style="margin-left:auto">${t.type}</span></div>`;
      }
    } else { html += emptyHtml('No recent activity'); }
    html += `</div></div></div>`;

    // Admin: user summaries
    if (isAdmin && d.user_summaries && d.user_summaries.length) {
      html += `<div class="card"><div class="card-header"><h3>Team Performance</h3></div><div class="card-body"><div class="table-wrap"><table>
        <thead><tr><th>User</th><th>Customers</th><th>Transactions</th><th>In Today</th><th>Out Today</th></tr></thead><tbody>`;
      for (const u of d.user_summaries) {
        html += `<tr><td><div class="row-name">${u.name}</div><div class="row-user">@${u.username} · ${u.role}</div></td>
          <td>${fmt.num(u.customers)}</td><td>${fmt.num(u.transactions)}</td>
          <td><span class="badge badge-green">${fmt.num(u.stock_in_today)}</span></td>
          <td><span class="badge badge-amber">${fmt.num(u.stock_out_today)}</span></td></tr>`;
      }
      html += `</tbody></table></div></div></div>`;
    }

    html += `</div></div>`;

    document.querySelector('.page-body').innerHTML = html;
  } catch(e) { document.querySelector('.page-body').innerHTML = `<p class="text-danger">Failed to load dashboard: ${e.message}</p>`; }
}

/* ═══════════════════════════════════════════════════════════════════════════
   INVENTORY
═══════════════════════════════════════════════════════════════════════════ */
let invData = [];
let invCustomerNames = [];

"""
