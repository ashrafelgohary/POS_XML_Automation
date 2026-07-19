"""POS XML Automation GUI.

Flask frontend for validating POS XML files and invoking the internal
Ansible Runner API. HTML, CSS and JavaScript are stored separately under
``templates`` and ``static``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import secrets
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

import requests
import urllib3
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename


# -----------------------------------------------------------------------------
# Configuration
# -----------------------------------------------------------------------------


def env_int(name: str, fallback_name: str | None, default: int) -> int:
    """Read a positive integer environment variable."""
    value = os.getenv(name)
    if value is None and fallback_name:
        value = os.getenv(fallback_name)
    try:
        number = int(value or default)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIRECTORY", "/app/incoming/new"))
LOG_DIR = Path(os.getenv("LOG_DIRECTORY", "/app/logs"))
ANSIBLE_API_URL = os.getenv(
    "ANSIBLE_API_URL", "http://ansible-runner:8000"
).rstrip("/")
RUNNER_API_TOKEN = os.getenv("RUNNER_API_TOKEN", "").strip()
MAX_UPLOAD_MB = env_int("MAX_UPLOAD_MB", "MAX_UPLOAD_SIZE_MB", 10)
REQUEST_TIMEOUT = env_int("REQUEST_TIMEOUT_SECONDS", None, 1800)
HEALTH_TIMEOUT = env_int("RUNNER_HEALTH_TIMEOUT", "HEALTH_TIMEOUT_SECONDS", 5)
VERIFY_RUNNER_TLS = os.getenv("VERIFY_RUNNER_TLS", "true").lower() == "true"
COMPANY_NAME = os.getenv("COMPANY_NAME", "Alshaya Group")
APP_TITLE = os.getenv("APP_TITLE", os.getenv("GUI_TITLE", "POS XML Automation"))
ENVIRONMENT_NAME = os.getenv("ENVIRONMENT_NAME", "Production")
TARGET_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,100}$")

if not VERIFY_RUNNER_TLS:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# -----------------------------------------------------------------------------
# Flask and logging
# -----------------------------------------------------------------------------

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32),
    MAX_CONTENT_LENGTH=MAX_UPLOAD_MB * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv(
        "SESSION_COOKIE_SECURE", "false"
    ).lower() == "true",
)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def configure_logging() -> None:
    """Use a rotating file log when writable; otherwise keep stderr logging."""
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            LOG_DIR / "gui-upload.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
    except OSError as exc:
        app.logger.warning("File logging unavailable: %s", exc)
        return

    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    handler.setLevel(logging.INFO)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


configure_logging()

retry_policy = Retry(
    total=2,
    connect=2,
    read=0,
    status=2,
    backoff_factor=0.5,
    status_forcelist=(502, 503, 504),
    allowed_methods=frozenset({"GET"}),
)
http = requests.Session()
http.mount("http://", HTTPAdapter(max_retries=retry_policy))
http.mount("https://", HTTPAdapter(max_retries=retry_policy))


# -----------------------------------------------------------------------------
# Security and validation helpers
# -----------------------------------------------------------------------------


def csrf_token() -> str:
    """Return the current browser session CSRF token."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return str(session["csrf_token"])


def valid_csrf(submitted: str) -> bool:
    """Compare the submitted and session CSRF tokens safely."""
    expected = str(session.get("csrf_token", ""))
    return bool(
        submitted
        and expected
        and secrets.compare_digest(submitted, expected)
    )


def runner_headers() -> dict[str, str]:
    """Build request headers for the internal Runner API."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-Request-ID": uuid.uuid4().hex,
    }
    if RUNNER_API_TOKEN:
        headers["Authorization"] = f"Bearer {RUNNER_API_TOKEN}"
    return headers


def runner_health() -> dict[str, Any]:
    """Return the availability of the internal Ansible Runner."""
    try:
        response = http.get(
            f"{ANSIBLE_API_URL}/health",
            headers=runner_headers(),
            timeout=HEALTH_TIMEOUT,
            verify=VERIFY_RUNNER_TLS,
        )
        return {
            "online": response.ok,
            "status": "Connected" if response.ok else "Unavailable",
        }
    except requests.RequestException:
        return {"online": False, "status": "Unavailable"}


def validate_target(target: str) -> str:
    """Validate an Ansible inventory host or group limit."""
    normalized = target.strip()
    if not TARGET_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Target may contain letters, numbers, dots, colons, "
            "underscores and hyphens only."
        )
    return normalized


def validate_xml(path: Path) -> dict[str, Any]:
    """
    Validate a POS Java-properties XML file safely.

    The standard Java properties DOCTYPE is permitted, but it is
    removed from the in-memory copy before parsing. ENTITY
    declarations and every other DOCTYPE remain forbidden.
    """

    raw = path.read_bytes()

    if not raw.strip():
        raise ValueError(
            "The uploaded XML file is empty."
        )

    allowed_doctype = (
        b'<!DOCTYPE properties SYSTEM '
        b'"http://java.sun.com/dtd/properties.dtd">'
    )

    # ENTITY declarations are never allowed.
    if re.search(
        br"<!ENTITY\b",
        raw,
        flags=re.IGNORECASE,
    ):
        raise ValueError(
            "ENTITY declarations are not allowed."
        )

    # Locate a DOCTYPE declaration, if one exists.
    doctype_match = re.search(
        br"<!DOCTYPE\s+[^>\[]+(?:\[[\s\S]*?\]\s*)?>",
        raw,
        flags=re.IGNORECASE,
    )

    parse_content = raw

    if doctype_match:
        declared_doctype = (
            doctype_match
            .group(0)
            .strip()
        )

        if declared_doctype != allowed_doctype:
            raise ValueError(
                "Only the standard Java properties "
                "DOCTYPE is allowed."
            )

        # Parse a memory-only copy without the external DTD.
        # The original uploaded file remains unchanged.
        parse_content = (
            raw[:doctype_match.start()]
            + raw[doctype_match.end():]
        )

    try:
        root = ET.fromstring(parse_content)
    except ET.ParseError as exc:
        raise ValueError(
            f"Invalid XML: {exc}"
        ) from exc

    root_name = str(root.tag).rsplit(
        "}",
        1,
    )[-1]

    if root_name != "properties":
        raise ValueError(
            "The root element must be <properties>."
        )

    entries = root.findall("entry")

    if not entries:
        raise ValueError(
            "The XML file does not contain any "
            "<entry> configuration elements."
        )

    for entry in entries:
        key = entry.get("key", "").strip()

        if not key:
            raise ValueError(
                "Every <entry> element must have "
                "a non-empty key attribute."
            )

    return {
        "root": root_name,
        "entries": len(entries),
        "size": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def save_xml(uploaded_file: Any) -> tuple[Path, dict[str, Any]]:
    """Save an XML upload with a safe unique filename, then validate it."""
    original = uploaded_file.filename or ""
    if not original.lower().endswith(".xml"):
        raise ValueError("Only .xml files are allowed.")

    safe_name = secure_filename(original)
    if not safe_name:
        raise ValueError("The uploaded filename is invalid.")

    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Upload directory is not writable: {UPLOAD_DIR}"
        ) from exc

    stored_name = (
        f"{Path(safe_name).stem[:70]}-"
        f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-"
        f"{uuid.uuid4().hex[:8]}.xml"
    )
    destination = UPLOAD_DIR / stored_name

    try:
        uploaded_file.save(destination)
        metadata = validate_xml(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise

    return destination, metadata


def execute_ansible(target: str, filename: str) -> dict[str, Any]:
    """Request staging and deployment from the internal Ansible Runner."""
    try:
        response = http.post(
            f"{ANSIBLE_API_URL}/run",
            headers=runner_headers(),
            json={
                "limit": target,
                "filename": filename,
                "run_staging": True,
            },
            timeout=REQUEST_TIMEOUT,
            verify=VERIFY_RUNNER_TLS,
        )
    except requests.Timeout as exc:
        raise RuntimeError("Ansible Runner request timed out.") from exc
    except requests.ConnectionError as exc:
        raise RuntimeError("Cannot connect to Ansible Runner.") from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Ansible Runner request failed: {exc}") from exc

    try:
        data = response.json()
    except ValueError as exc:
        raise RuntimeError("Ansible Runner returned a non-JSON response.") from exc

    if not response.ok:
        detail = data.get("detail", f"HTTP {response.status_code}")
        raise RuntimeError(f"Ansible Runner rejected the request: {detail}")

    ansible = data.get("ansible") or {}
    output = "\n".join(
        part
        for part in (
            str(ansible.get("stdout", "")),
            str(ansible.get("stderr", "")),
        )
        if part
    )
    return {
        "status": str(data.get("status", "unknown")),
        "execution_id": str(data.get("execution_id", "not provided")),
        "output": output[-50000:],
    }


def page_context(result: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return values used by templates/index.html."""
    return {
        "app_title": APP_TITLE,
        "page_title": APP_TITLE,
        "gui_title": APP_TITLE,
        "company_name": COMPANY_NAME,
        "environment_name": ENVIRONMENT_NAME,
        "max_upload_mb": MAX_UPLOAD_MB,
        "max_upload_size_mb": MAX_UPLOAD_MB,
        "runner": runner_health(),
        "ansible_health": runner_health(),
        "csrf_token": csrf_token(),
        "result": result,
        "execution_result": result,
    }


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.get("/")
def index():
    return render_template("index.html", **page_context())


@app.post("/upload")
def upload():
    if not valid_csrf(request.form.get("csrf_token", "")):
        flash("Session expired. Refresh the page and try again.", "error")
        return redirect(url_for("index"))

    try:
        target = validate_target(request.form.get("target", ""))
        uploaded_file = request.files.get("xml_file")
        if uploaded_file is None:
            raise ValueError("Select an XML file.")

        destination, metadata = save_xml(uploaded_file)
        runner_result = execute_ansible(target, destination.name)
        result = {
            **runner_result,
            "target": target,
            "filename": destination.name,
            **metadata,
        }

        app.logger.info(
            "Deployment target=%s file=%s status=%s execution_id=%s",
            target,
            destination.name,
            result["status"],
            result["execution_id"],
        )

        success = result["status"].lower() == "success"
        flash(
            "XML validated and deployment completed."
            if success
            else "Deployment returned a non-success status.",
            "success" if success else "error",
        )
        return render_template(
            "index.html", **page_context(result=result)
        ), 200 if success else 502

    except (ValueError, RuntimeError, OSError) as exc:
        app.logger.warning("Request rejected: %s", exc)
        flash(str(exc), "error")
        return redirect(url_for("index"))


@app.get("/health")
def health():
    runner = runner_health()
    return jsonify(
        service="pos-xml-gui",
        status="healthy",
        runner="connected" if runner["online"] else "unavailable",
    )


@app.get("/api/status")
def api_status():
    return jsonify(runner_health())


@app.errorhandler(RequestEntityTooLarge)
def file_too_large(_error):
    flash(f"File exceeds the {MAX_UPLOAD_MB} MB limit.", "error")
    return render_template("index.html", **page_context()), 413


@app.after_request
def security_headers(response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "style-src 'self'; "
        "script-src 'self'; "
        "img-src 'self' data:; "
        "frame-ancestors 'none'; "
        "form-action 'self'"
    )
    if request.path not in {"/health", "/api/status"}:
        response.headers["Cache-Control"] = "no-store, max-age=0"
    return response


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
