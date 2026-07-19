# POS XML Automation GUI

## Validate

```bash
python3 -m py_compile app.py
```

## Required files

- `app.py`
- `templates/index.html`
- `static/css/style.css`
- `static/js/app.js`
- `requirements.txt`
- `Dockerfile`

## Run with Docker Compose

Mount this directory as `/app/gui_upload`, and mount writable `incoming` and `logs` directories. The GUI expects the Ansible Runner API at `ANSIBLE_API_URL`.
