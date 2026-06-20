# WMS Category Folder Map

`app.py` is the main linking/tunnel file. It imports shared setup from
`wms_core.py`, then links every category folder directly.

Each category folder has one main category file. That file contains:

- the backend Flask routes for that category
- a `FRONTEND_REFERENCE` block copied from `ms-warehouse-frontend/index.html`
  showing the matching frontend screen/functions

The original frontend still runs from `ms-warehouse-frontend/index.html`, so the
app behavior stays the same. The category file gives you one place to share when
you want edits for that area.

## Main files

- `app.py` - main tunnel/linking file.
- `wms_core.py` - shared app setup, data paths, JSON helpers, auth decorators,
  default data, customer access helpers, and CORS setup.
- `ms-warehouse-frontend/index.html` - active frontend page.

## Category folders

- `auth_users/auth_users.py` - login/logout, current user, user management, and
  login/user-management frontend reference.
- `dashboard/dashboard.py` - dashboard backend and dashboard frontend reference.
- `inventory/inventory.py` - inventory backend and inventory frontend reference.
- `stock_io/stock_io.py` - inbound/outbound stock movement backend and frontend
  reference.
- `customers/customers.py` - customer backend and customer frontend reference.
- `billing/billing.py` - billing backend and billing frontend reference.
- `templates/templates.py` - Excel template backend and template frontend reference.
- `export_reports/export_reports.py` - report/export backend and report/export
  frontend reference.
- `settings_logs/settings_logs.py` - settings/log backend and frontend reference.
- `file_imports/file_imports.py` - upload/import backend and template/file-import
  frontend reference.

## How to work category wise

1. Share only the category folder file you want changed, for example
   `inventory/inventory.py`.
2. Edit that one file for backend route changes and use its `FRONTEND_REFERENCE`
   block to identify the matching frontend code.
3. If frontend behavior changes, copy the edited frontend function back into
   `ms-warehouse-frontend/index.html`.
4. Replace the category file in the same folder and restart Flask.
5. `app.py` automatically links the category again during startup.

The API paths are unchanged (`/api/inventory`, `/api/transactions`,
`/api/customers`, etc.), so existing frontend API calls remain linked.
