# POS XML Automation Platform

> Centralized, containerized configuration management for Point-of-Sale (POS) terminals — powered by **Ansible**, a **Flask** web GUI, and an **Nginx** reverse proxy.

---

## Table of Contents

1. [Overview](#overview)
2. [Key Features](#key-features)
3. [High-Level Architecture](#high-level-architecture)
4. [Component Breakdown](#component-breakdown)
5. [Request & Deployment Flow](#request--deployment-flow)
6. [Directory Structure](#directory-structure)
7. [Why Containerize Ansible?](#why-containerize-ansible)
8. [The Ansible Runner API](#the-ansible-runner-api)
9. [How the Playbook Works](#how-the-playbook-works)
10. [How the GUI Works with Ansible](#how-the-gui-works-with-ansible)
11. [The Reverse Proxy Layer](#the-reverse-proxy-layer)
12. [Secrets & Ansible Vault](#secrets--ansible-vault)
13. [Deployment Guide](#deployment-guide)
14. [Operations & Maintenance](#operations--maintenance)
15. [Security Hardening](#security-hardening)
16. [Troubleshooting](#troubleshooting)

---

## Overview

The **POS XML Automation Platform** provides a single, secure, web-based control point to push standardized XML configuration files (`MarshalPOS.XML`) to a fleet of Linux-based POS terminals across retail stores.

Instead of manually copying configuration files to each terminal over SSH, an operator simply:

1. Opens a clean web page (no IP or port exposed).
2. Uploads a POS XML configuration file.
3. Selects the target device or store group.
4. Clicks **Deploy**.

Behind the scenes, a **containerized Ansible control node** validates, stages, and pushes the configuration to the correct POS terminal(s), reboots them if the file actually changed, and returns the execution result to the browser.

The entire stack runs as **Docker containers** orchestrated by **Docker Compose**, so it can be built once and shipped to any production server as a self-contained bundle.

---

## Key Features

| Capability | Description |
|------------|-------------|
| 🖥️ **Web GUI** | Drag-and-drop XML upload with company branding, no CLI required. |
| 🐳 **Containerized Ansible** | Ansible runs inside Docker — no host-level installation or version drift. |
| 🎯 **Central Management** | One control node manages the entire POS fleet via SSH. |
| 🔐 **Encrypted Secrets** | SSH & sudo passwords stored with Ansible Vault, never in plain text. |
| 🔄 **Idempotent Deploys** | POS reboots **only** when the configuration file actually changes. |
| 🌐 **Reverse Proxy** | Nginx hides internal IPs/ports and exposes a single clean endpoint. |
| 🧩 **API-Driven** | GUI ↔ Ansible communication over an internal token-authenticated HTTP API. |
| 📦 **Portable Build** | Ship the whole platform as compressed Docker images + compose file. |

---

## High-Level Architecture

```text
                          ┌─────────────────────────────────────────────┐
                          │                 OPERATOR                     │
                          │        Browser → http://pos.alshaya.local    │
                          └───────────────────────┬─────────────────────┘
                                                  │  HTTP (port 80)
                                                  │  clean URL — no IP:port
                                                  ▼
        ╔══════════════════════════════════════════════════════════════════════╗
        ║                        DOCKER HOST (Production Server)                 ║
        ║                                                                        ║
        ║   ┌──────────────────────────────────────────────────────────────┐   ║
        ║   │                      pos-automation network                   │   ║
        ║   │                        (internal bridge)                      │   ║
        ║   │                                                                │   ║
        ║   │   ┌───────────────┐                                           │   ║
        ║   │   │  nginx        │  ← ONLY container with published ports    │   ║
        ║   │   │  :80  (public)│    (80/443 → host)                        │   ║
        ║   │   └───────┬───────┘                                           │   ║
        ║   │           │ proxy_pass http://gui-upload:5000                 │   ║
        ║   │           ▼                                                    │   ║
        ║   │   ┌───────────────┐      POST /run (Bearer token)             │   ║
        ║   │   │  gui-upload   │ ───────────────────────────────┐          │   ║
        ║   │   │  Flask :5000  │                                 │          │   ║
        ║   │   │  (expose only)│                                 ▼          │   ║
        ║   │   └───────┬───────┘                        ┌────────────────┐ │   ║
        ║   │           │                                │ ansible-runner │ │   ║
        ║   │           │  shared volume: ./incoming     │ FastAPI :8000  │ │   ║
        ║   │           └───────────────────────────────▶│ (expose only)  │ │   ║
        ║   │                                            │  + Ansible     │ │   ║
        ║   │                                            └───────┬────────┘ │   ║
        ║   └────────────────────────────────────────────────────┼──────────┘   ║
        ║                                                         │              ║
        ╚═════════════════════════════════════════════════════════┼══════════════╝
                                                                  │  SSH (key/vault)
                          ┌───────────────────────────────────────┼───────────────┐
                          ▼                     ▼                  ▼               ▼
                   ┌────────────┐        ┌────────────┐    ┌────────────┐   ┌────────────┐
                   │  POS-001   │        │  POS-002   │    │  POS-003   │   │  POS-NNN   │
                   │ Linux + SSH│        │ Linux + SSH│    │ Linux + SSH│   │ Linux + SSH│
                   │/var/epos/  │        │/var/epos/  │    │/var/epos/  │   │/var/epos/  │
                   │ MarshalPOS │        │ MarshalPOS │    │ MarshalPOS │   │ MarshalPOS │
                   │   .XML     │        │   .XML     │    │   .XML     │   │   .XML     │
                   └────────────┘        └────────────┘    └────────────┘   └────────────┘
```

### Network Exposure Summary

| Container | Internal Port | Published to Host? | Reachable From |
|-----------|--------------|--------------------|----------------|
| `nginx` | 80 | ✅ Yes (`80:80`) | The whole network |
| `gui-upload` | 5000 | ❌ No (`expose` only) | Nginx only |
| `ansible-runner` | 8000 | ❌ No (`expose` only) | GUI only |

> This is the core security principle: **only Nginx is public**. The Flask GUI and the Ansible API are invisible to the outside world and can only be reached through the internal Docker bridge network.

---

## Component Breakdown

### 1. Nginx (Reverse Proxy)

- The single public entry point (port 80).
- Terminates the client connection and forwards requests to the GUI via the internal DNS name `gui-upload:5000`.
- Hides the real container IPs and ports.
- Adds security headers and enforces the upload size limit.
- Injects `X-Forwarded-*` headers so Flask knows the original client and scheme.

### 2. GUI (Flask + Gunicorn)

- A branded, responsive web application (`gui-upload` container).
- Handles file upload, client-side and server-side XML validation, and the deployment form.
- Saves validated XML into a **shared Docker volume** (`./incoming`).
- Calls the Ansible Runner API over the internal network with a **Bearer token**.
- Renders the deployment result (success/failure + Ansible output).

### 3. Ansible Runner (FastAPI + Ansible)

- The **containerized control node** (`ansible-runner` container).
- Exposes a small internal HTTP API (`/health`, `/run`).
- On `/run`, it:
  1. Authenticates the Bearer token.
  2. Runs the staging script to place the XML into `pos-configs/`.
  3. Executes the Ansible playbook against the requested target.
  4. Writes an execution log and returns JSON.
- Connects to POS terminals over **SSH** using credentials decrypted from **Ansible Vault**.

### 4. POS Terminals (Managed Nodes)

- Linux-based POS devices reachable over SSH.
- Receive the configuration at `/var/epos/bin/MarshalPOS.XML`.
- Rebooted **only** if the pushed file differs from the existing one.

---

## Request & Deployment Flow

```text
 Operator        Nginx         GUI (Flask)        Runner (FastAPI)         POS Device
    │              │                │                     │                     │
    │ 1. Open page │                │                     │                     │
    ├─────────────▶│                │                     │                     │
    │              │ 2. proxy_pass  │                     │                     │
    │              ├───────────────▶│                     │                     │
    │              │                │ 3. render page      │                     │
    │◀─────────────┴────────────────┤                     │                     │
    │                               │                     │                     │
    │ 4. Upload XML + target + Deploy│                     │                     │
    ├──────────────▶(via Nginx)────▶│                     │                     │
    │                               │ 5. validate XML     │                     │
    │                               │ 6. save to ./incoming (shared volume)     │
    │                               │ 7. POST /run  ──────▶│                     │
    │                               │   (Bearer token)    │ 8. auth token       │
    │                               │                     │ 9. stage XML →      │
    │                               │                     │    pos-configs/     │
    │                               │                     │ 10. ansible-playbook│
    │                               │                     ├────── SSH ─────────▶│
    │                               │                     │ 11. push MarshalPOS │
    │                               │                     │     .XML + reboot?  │
    │                               │                     │◀──── result ────────┤
    │                               │ 12. JSON result ◀───┤                     │
    │ 13. show success/failure ◀────┤                     │                     │
    │◀──────────────(via Nginx)─────┤                     │                     │
```

---

## Directory Structure

```text
POS_XML_Automation/
├── docker-compose.yml              # Orchestrates nginx + gui + runner
├── .env                            # Secrets (RUNNER_API_TOKEN, FLASK_SECRET_KEY)
├── .vault_pass                     # Ansible Vault password file (chmod 600)
│
├── nginx/
│   ├── conf.d/
│   │   └── pos.conf                # Reverse proxy configuration
│   └── logs/                       # Nginx access/error logs
│
├── gui_upload/                     # Flask web application
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── app.py                      # Routes, validation, Runner API client
│   ├── templates/
│   │   └── index.html              # Web UI markup
│   └── static/
│       ├── css/style.css           # Company-branded styling
│       └── js/app.js               # Drag-and-drop + submit logic
│
├── ansible/                        # Containerized Ansible control node
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── runner_api.py               # FastAPI wrapper around ansible-playbook
│   └── site.yml                    # The deployment playbook
│
├── inventory/
│   ├── hosts.yml                   # POS device inventory
│   └── group_vars/
│       └── all/
│           ├── all.yml             # Shared vars (user, become, paths)
│           └── vault.yml           # Encrypted SSH/sudo password
│
├── scripts/
│   └── stage_pos_xmls.py           # Stages uploaded XML → pos-configs/
│
├── pos-configs/                    # Staged, ready-to-push XML files
├── incoming/
│   ├── new/                        # GUI drops uploaded XML here
│   └── archive/                    # Processed uploads archived here
└── logs/                           # Ansible execution logs
```

---

## Why Containerize Ansible?

Running Ansible inside a container instead of directly on the host provides:

| Benefit | Explanation |
|---------|-------------|
| **Version pinning** | The image locks a specific `ansible-core` version (e.g. `2.16.14`) compatible with the POS terminals' Python (3.6.8). No accidental upgrades break deployments. |
| **Reproducibility** | The exact same environment runs on the test server and the production server. |
| **Isolation** | Ansible, its Python deps, `sshpass`, and `rsync` are sealed inside the image — the host stays clean. |
| **Portability** | `docker save` / `docker load` moves the entire control node to an air-gapped production server. |
| **Least privilege** | The container runs as a non-root user (UID `10001`) with `no-new-privileges`. |

> ⚠️ **Compatibility note:** POS terminals run **Python 3.6.8**. Modern `ansible-core` (2.21.x) generates modules with `from __future__ import annotations`, which is invalid on Python < 3.7. The image therefore pins **`ansible-core 2.16.14`** to stay compatible with the managed nodes.

---

## The Ansible Runner API

The `ansible-runner` container wraps `ansible-playbook` behind a minimal **FastAPI** service. This is deliberately chosen **instead of mounting the Docker socket** into the GUI (which would give the web app root-level control of the host).

### Endpoints

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| `GET` | `/health` | none | Liveness + checks inventory/playbook/staging files exist. |
| `POST` | `/run` | Bearer token | Stage XML and run the playbook against a target. |

### `/run` Request Body

```json
{
  "limit": "pos-001",
  "filename": "MarshalPOS-242FFA156998.xml",
  "run_staging": true
}
```

### Command the API Builds

```python
ansible_command = [
    "ansible-playbook",
    "-i", str(INVENTORY_FILE),
    str(PLAYBOOK_FILE),
    "--limit", request.limit,
    "--vault-password-file", "/app/.vault_pass",
]
```

### Authentication

The GUI sends:

```http
Authorization: Bearer <RUNNER_API_TOKEN>
```

The Runner compares it against its own `RUNNER_API_TOKEN` environment variable. Both containers read the **same** value from the shared `.env` file, guaranteeing they match.

---

## How the Playbook Works

The playbook (`ansible/site.yml`) runs against the target POS device(s) and performs an **idempotent** configuration push.

### Stage 0 — Group Variables (`inventory/group_vars/all/all.yml`)

```yaml
# Where staged XMLs live on the control node (inside the container)
pos_configs_dir: "{{ playbook_dir | dirname }}/pos-configs"

# Final destination on each POS terminal
pos_config_dest: "/var/epos/bin/MarshalPOS.XML"

# SSH connection
ansible_user: "ashraf"
ansible_password: "{{ vault_ssh_password }}"        # from vault.yml
ansible_ssh_common_args: "-o StrictHostKeyChecking=no"

# Privilege escalation (sudo uses the same password)
become: true
become_method: sudo
become_user: root
ansible_become_password: "{{ vault_ssh_password }}"  # from vault.yml

# Read the terminal's MAC from its NIC
pos_mac_cmd: "cat /sys/class/net/eno1/address"

# Reboot only when the config actually changed
reboot_on_change: true

ansible_forks: 20
```

### Stage 1 — Discover the POS MAC Address

The playbook reads the terminal's MAC address directly from the network interface. Because the POS runs an older Python, this step uses the **`raw`** module (which needs no Python on the target):

```yaml
- name: Discover MAC address on POS (eno1)
  raw: cat /sys/class/net/eno1/address
  register: pos_mac
  changed_when: false
```

### Stage 2 — Normalize the MAC

The MAC is normalized (colons removed, uppercased) to match the staged filename convention, e.g. `242FFA156998`:

```yaml
- name: Normalize MAC
  set_fact:
    pos_mac_norm: "{{ pos_mac.stdout | trim | replace(':','') | upper }}"
```

### Stage 3 — Verify the Staged File Exists on the Controller

This task runs on the **control node itself** (`delegate_to: localhost`) and must **not** use sudo — it simply confirms the staged XML is present:

```yaml
- name: Ensure staged XML exists on controller
  stat:
    path: "{{ pos_configs_dir }}/{{ pos_mac_norm }}.xml"
  delegate_to: localhost
  become: false        # ← critical: no sudo inside the container
  register: staged_xml
```

> 🔎 **Lesson learned:** localhost tasks inherit the play-level `become: true`. Inside a hardened container (`no-new-privileges`), `sudo` is blocked, so controller-side tasks must explicitly set `become: false`.

### Stage 4 — Push the Configuration to the POS

The matching XML is copied to the terminal. Ansible's `copy` module is **idempotent** — it reports `changed` only when the file content actually differs:

```yaml
- name: Deploy MarshalPOS.XML to the terminal
  copy:
    src: "{{ pos_configs_dir }}/{{ pos_mac_norm }}.xml"
    dest: "{{ pos_config_dest }}"
    owner: root
    group: root
    mode: "0644"
  register: config_push
```

### Stage 5 — Conditional Reboot

The terminal reboots **only** when the config changed **and** `reboot_on_change` is enabled — avoiding unnecessary downtime:

```yaml
- name: Reboot POS if configuration changed
  reboot:
    reboot_timeout: 300
  when:
    - reboot_on_change | bool
    - config_push is changed
```

### Idempotency in Action

| Scenario | `copy` result | Reboot? |
|----------|--------------|---------|
| New/different XML pushed | `changed` | ✅ Yes |
| Identical XML already present | `ok` (unchanged) | ❌ No |

---

## How the GUI Works with Ansible

The GUI is intentionally **decoupled** from Ansible. It never runs `ansible-playbook` itself — it delegates to the Runner API. This keeps the web tier lightweight and prevents it from needing host or Docker privileges.

### Step-by-step

1. **Upload** — The operator drops an XML file and enters a target (e.g. `pos-001`).
2. **Validate** — `app.py` checks:
   - File extension is `.xml`.
   - File size is within `MAX_UPLOAD_MB`.
   - Filename is sanitized with `secure_filename()`.
   - XML parses correctly.
   - **DOCTYPE policy:** the standard Java Properties DOCTYPE
     (`<!DOCTYPE properties SYSTEM "http://java.sun.com/dtd/properties.dtd">`)
     is allowed, but any `<!ENTITY>` declaration or other DOCTYPE is rejected (XXE protection).
   - Root element is `<properties>` with valid `<entry>` keys.
3. **Stage** — The validated file is written to the shared `./incoming/new` volume.
4. **Trigger** — The GUI issues `POST /run` to `http://ansible-runner:8000` with the Bearer token.
5. **Wait** — Gunicorn holds the request open (long timeout) while Ansible executes.
6. **Render** — The JSON result (status, execution ID, Ansible stdout/stderr) is displayed.

### Shared Volume Bridge

The GUI and the Runner **both mount the same host directory**:

```yaml
# gui-upload
volumes:
  - ./incoming:/app/incoming

# ansible-runner
volumes:
  - ./incoming:/app/incoming
```

This means the file the GUI saves is instantly visible to the Runner — **no file copying between containers is needed**.

### Trusting the Proxy

Because the GUI sits behind Nginx, `app.py` uses Werkzeug's `ProxyFix` so Flask correctly reads the original client IP and scheme from the `X-Forwarded-*` headers:

```python
from werkzeug.middleware.proxy_fix import ProxyFix

app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1, x_proto=1, x_host=1,
)
```

---

## The Reverse Proxy Layer

Nginx provides a clean, single endpoint and hides all internal topology.

### `nginx/conf.d/pos.conf`

```nginx
server {
    listen 80;
    server_name _;

    client_max_body_size 15M;

    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "no-referrer" always;

    location / {
        proxy_pass http://gui-upload:5000;
        proxy_http_version 1.1;

        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Long timeouts for lengthy Ansible runs
        proxy_connect_timeout 60s;
        proxy_send_timeout   1900s;
        proxy_read_timeout   1900s;
    }

    access_log /var/log/nginx/pos-access.log;
    error_log  /var/log/nginx/pos-error.log;
}
```

### What it achieves

- **Clean URL:** operators use `http://pos.alshaya.local` — no `:5000`, no raw IP.
- **Port hiding:** the GUI (`5000`) and Runner (`8000`) use `expose` (internal only), never `ports`.
- **Central choke point:** security headers, body-size limits, logging, and (optionally) rate limiting and basic auth all live in one place.
- **Long-run friendly:** the `1900s` read timeout accommodates lengthy playbook executions.

### Internal DNS Resolution

Docker Compose creates the `pos-automation` bridge network. Containers resolve each other by **service name**:

- Nginx → `gui-upload:5000`
- GUI → `ansible-runner:8000`

No hard-coded IPs anywhere.

---

## Secrets & Ansible Vault

Sensitive values are **never** stored in plain text in the repo or compose file.

| Secret | Where it lives | How it's used |
|--------|---------------|---------------|
| `RUNNER_API_TOKEN` | `.env` | Authenticates GUI → Runner API. |
| `FLASK_SECRET_KEY` | `.env` | Flask session/CSRF signing. |
| POS SSH/sudo password | `inventory/group_vars/all/vault.yml` (encrypted) | Decrypted at runtime by Ansible. |
| Vault password | `.vault_pass` (`chmod 600`) | Decrypts `vault.yml`. |

### Creating the Vault

```bash
# Inside the runner container (no editor needed)
cat > /tmp/vault_plain.yml <<'EOF'
vault_ssh_password: "YOUR_POS_SSH_PASSWORD"
EOF

ansible-vault encrypt /tmp/vault_plain.yml \
  --output inventory/group_vars/all/vault.yml \
  --vault-password-file /app/.vault_pass

rm /tmp/vault_plain.yml
```

### Critical `.vault_pass` Rules

- Must be a **file**, not a directory (an empty bind-mount target becomes a directory).
- Must be **`chmod 600`** — if it has the execute bit, Ansible tries to *run* it as a script and fails with `Permission denied`.
- Must contain the password with **no trailing newline** (use `printf`, not `echo`).

```bash
printf 'YOUR_VAULT_PASSWORD' > .vault_pass
sudo chown 10001:10001 .vault_pass
sudo chmod 600 .vault_pass
```

---

## Deployment Guide

### Prerequisites

- Docker Engine 24+ with the Compose plugin.
- Network/SSH reachability from the Docker host to POS terminals.
- Ports 80 (and optionally 443) free on the host.

### A. Build on a connected machine

```bash
cd POS_XML_Automation
docker compose build --no-cache
```

### B. Export images for an air-gapped production server

```bash
docker save pos-xml-automation-ansible:latest | gzip > pos-xml-ansible.tar.gz
docker save pos-xml-automation-gui:latest     | gzip > pos-xml-gui.tar.gz
```

> If your build corporate proxy blocks Docker Hub TLS, the correct fix is trusting the corporate root CA on the host. If that's not possible, build on a connected machine and transfer the images with `docker save` / `docker load` as above.

### C. Load on the production server

```bash
gunzip -c pos-xml-ansible.tar.gz | docker load
gunzip -c pos-xml-gui.tar.gz     | docker load
```

### D. Prepare host directories & permissions

```bash
sudo mkdir -p incoming/new incoming/archive logs pos-configs
sudo chown -R 10001:10001 incoming pos-configs logs inventory ansible scripts
sudo chmod -R 775 incoming pos-configs logs
```

### E. Create secrets

```bash
# .env
cat > .env <<EOF
RUNNER_API_TOKEN=$(openssl rand -hex 32)
FLASK_SECRET_KEY=$(openssl rand -hex 32)
EOF
chmod 600 .env

# .vault_pass
printf 'YOUR_VAULT_PASSWORD' > .vault_pass
sudo chown 10001:10001 .vault_pass
sudo chmod 600 .vault_pass
```

### F. Launch

```bash
docker compose up -d
docker compose ps
```

Expected:

```text
pos-xml-nginx     Up             0.0.0.0:80->80/tcp
pos-xml-ansible   Up (healthy)   8000/tcp
pos-xml-gui       Up (healthy)   5000/tcp
```

### G. Verify

```bash
curl http://localhost/health
# {"runner":"connected","service":"pos-xml-gui","status":"healthy"}
```

Then browse to `http://<server-ip>` (or your `hosts`-mapped domain).

---

## Operations & Maintenance

```bash
# Start / stop / restart
docker compose up -d
docker compose down
docker compose restart

# Live logs
docker compose logs -f
docker compose logs -f gui-upload
docker compose logs -f ansible-runner

# Test SSH reachability to a POS
docker exec pos-xml-ansible \
  ansible pos-001 -i /app/inventory/hosts.yml -m ping \
  --vault-password-file /app/.vault_pass

# Run the playbook manually (debug with -vvv)
docker exec pos-xml-ansible \
  ansible-playbook -i /app/inventory/hosts.yml /app/ansible/site.yml \
  --limit pos-001 --vault-password-file /app/.vault_pass -vvv

# Backup critical state
tar czf backup-$(date +%Y%m%d).tar.gz inventory/ .env .vault_pass logs/
```

---

## Security Hardening

| Control | Implementation |
|---------|----------------|
| **No public app ports** | GUI/Runner use `expose`; only Nginx publishes `80`. |
| **Non-root containers** | GUI runs as UID `10002`, Runner as UID `10001`. |
| **`no-new-privileges`** | Set on every service to block privilege escalation. |
| **Token-authenticated API** | GUI → Runner requires a Bearer token from `.env`. |
| **Encrypted credentials** | POS SSH/sudo password via Ansible Vault. |
| **XXE protection** | Only the standard Java Properties DOCTYPE allowed; `ENTITY` rejected. |
| **No Docker socket exposure** | GUI talks to Ansible via HTTP API, not `/var/run/docker.sock`. |
| **Firewall** | Allow `80`, deny `5000`/`8000` at the host firewall. |

```bash
sudo ufw allow 80/tcp
sudo ufw deny 5000/tcp
sudo ufw deny 8000/tcp
```

> 🔐 **Credential hygiene:** Any password ever typed into a chat, screenshot, or shared note must be rotated on the POS fleet and stored only in Ansible Vault.

---

## Troubleshooting

| Symptom | Root Cause | Fix |
|---------|-----------|-----|
| `Could not import module "runner_api"` | Uvicorn started outside `/app/ansible` | `WORKDIR /app/ansible` in Dockerfile (or `--app-dir /app/ansible`). |
| `future feature annotations is not defined` | `ansible-core` too new for POS Python 3.6 | Pin `ansible-core==2.16.14`. |
| `Invalid API token` / `401` | GUI & Runner tokens differ or header not read | Same `RUNNER_API_TOKEN` in `.env`; use `Header(default=None)` in FastAPI. |
| `Ansible Runner returned a non-JSON response` | Runner threw a 500 (e.g. log write error) | Fix host permissions on `logs/`, `incoming/`, `pos-configs/`. |
| `sudo: not found` / `no new privileges` | localhost task inheriting `become: true` | Set `become: false` on controller-side tasks. |
| `Permission denied: /app/...` | Bind-mounted dir not owned by container UID | `chown -R 10001:10001` on the host. |
| `vault password ... Permission denied` | `.vault_pass` has execute bit | `chmod 600 .vault_pass`. |
| `.vault_pass: Is a directory` | Bind mount created an empty dir | Delete it, recreate as a file with `printf`. |
| `DOCTYPE ... not allowed` for valid POS XML | Validator rejected the standard Java DTD | Allow the standard Properties DOCTYPE, keep rejecting `ENTITY`. |

---

## License & Ownership

Internal tool — **Alshaya Group**. For authorized internal use only. Do not commit `.env`, `.vault_pass`, or `vault.yml` to source control.

---

*Maintained by the Systems Support Engineering team.*

