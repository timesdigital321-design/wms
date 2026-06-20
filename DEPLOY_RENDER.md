# Deploy WMS on Render.com

## Render settings

- Service type: Web Service
- Environment: Python
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn wsgi:app --bind 0.0.0.0:$PORT`

## Default login

- Username: `admin`
- Password: `admin123`

## Important data note

This app stores data in local JSON files and uploaded files on disk. On Render free services, disk data can be lost on redeploy/rebuild. For real use, add a Render persistent disk or later migrate storage to a database/object storage.
