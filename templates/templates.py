"""Templates routes for the WMS backend."""

from wms_core import *

@app.route("/api/templates", methods=["GET"])
@require_admin
def list_templates():
    headers = load_json(TEMPL_HEADERS_FILE, default_template_headers())
    templates = []
    for f in TEMPL_DIR.glob("*.xlsx"):
        tpl_key = f.stem.replace("_template", "").replace("-", "_")
        templates.append({
            "filename": f.name,
            "key": tpl_key,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "headers": headers.get(tpl_key, {})
        })
    # Also include virtual templates
    for key in headers:
        if not any(t["key"] == key for t in templates):
            templates.append({"filename": None, "key": key, "size_kb": 0,
                               "headers": headers.get(key, {})})
    return jsonify({"templates": templates, "all_headers": headers})

@app.route("/api/templates/headers", methods=["GET"])
@require_admin
def get_template_headers():
    return jsonify(load_json(TEMPL_HEADERS_FILE, default_template_headers()))

@app.route("/api/templates/headers", methods=["PUT"])
@require_admin
def update_template_headers():
    """Admin can edit the column heading labels for any template."""
    data = request.json or {}
    headers = load_json(TEMPL_HEADERS_FILE, default_template_headers())
    changed = []
    for tpl_key, cols in data.items():
        if tpl_key in headers and isinstance(cols, dict):
            for col, label in cols.items():
                clean_label = str(label).strip()
                if clean_label:
                    headers[tpl_key][col] = clean_label
                    changed.append(f"{tpl_key}.{col}={clean_label}")
    save_json(TEMPL_HEADERS_FILE, headers)
    log_activity(request.current_user["username"], "Updated template headers", "Templates",
                 "; ".join(changed[:10]))
    return jsonify(headers)


@app.route("/api/templates/defaults", methods=["GET"])
@require_admin
def get_default_template_headers():
    """Return built-in template headers so the UI can show/reset defaults."""
    return jsonify(default_template_headers())

@app.route("/api/templates/reset-defaults", methods=["POST"])
@require_admin
def reset_template_headers():
    """Reset editable template headers back to the built-in defaults."""
    defaults = default_template_headers()
    save_json(TEMPL_HEADERS_FILE, defaults)
    log_activity(request.current_user["username"], "Reset template headers", "Templates",
                 "Template headers restored to defaults", status="warning")
    return jsonify(defaults)

@app.route("/api/templates/<key>/headers", methods=["GET"])
@require_admin
def get_single_template_headers(key):
    """Shortcut: headers for one template key, e.g. GET /api/templates/inventory/headers."""
    headers = load_json(TEMPL_HEADERS_FILE, default_template_headers())
    if key not in headers:
        return jsonify({"error": f"Unknown template key '{key}'"}), 404
    return jsonify(headers[key])

@app.route("/api/templates/<filename>", methods=["GET"])
@require_admin
def download_template(filename):
    safe = Path(filename).name
    path = TEMPL_DIR / safe
    if not path.exists() or path.suffix != ".xlsx":
        return jsonify({"error": "Template not found"}), 404
    return send_file(path, as_attachment=True, download_name=safe)

@app.route("/api/templates/generate/<tpl_key>", methods=["GET"])
@require_admin
def generate_template(tpl_key):
    """Generate a fresh Excel template using the current custom headings."""
    headers = load_json(TEMPL_HEADERS_FILE, default_template_headers())
    if tpl_key not in headers:
        return jsonify({"error": "Unknown template key"}), 404
    col_headers = headers[tpl_key]
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = tpl_key.replace("_", " ").title()
    header_fill = PatternFill(start_color="1F4E79", end_color="1F4E79", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True, size=11)
    for col_idx, (_, label) in enumerate(col_headers.items(), start=1):
        cell = ws.cell(row=1, column=col_idx, value=label)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(col_idx)].width = max(len(label) + 4, 15)
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    log_activity(request.current_user["username"], "Downloaded template", "File Log",
                 f"{tpl_key}_template.xlsx",
                 meta={"file_type": "template", "file_status": "done",
                       "direction": "download", "file_name": f"{tpl_key}_template.xlsx"})
    return send_file(buf, as_attachment=True,
                     download_name=f"{tpl_key}_template.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


# Frontend reference copied from ms-warehouse-frontend/index.html.
# Keep this block with the category so this one file can be shared for changes.
FRONTEND_REFERENCE = r"""
  { id:'templates',  label:'Templates',    icon:'templates',  module:'Templates', adminOnly:true },
  { id:'users',      label:'Users',        icon:'users',      module:'Users',      adminOnly:true },
  { id:'export',     label:'Export',       icon:'export',     module:'Export' },

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
      html += `<button type="button" class="btn btn-ghost btn-sm" onclick="downloadTemplate('${key}')">${icon.export} ${key.replace(/_/g,' ')}</button>`;
    }
    html += `</div></div></div>`;

    document.getElementById('tmpl-body').innerHTML = html;
  } catch(e) { document.getElementById('tmpl-body').innerHTML=`<p class="text-danger">${e.message}</p>`; }
}

async function downloadTemplate(key) {
  const token = localStorage.getItem('wms_token');
  try {
    const response = await fetch(`/api/templates/generate/${encodeURIComponent(key)}`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || `Download failed (${response.status})`);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${key}_template.xlsx`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    toast('Template downloaded','success');
  } catch(e) {
    toast(e.message, 'error');
  }
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

