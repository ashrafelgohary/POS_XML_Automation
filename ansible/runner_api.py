import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="POS XML Ansible Runner",
    version="1.0.0"
)

PROJECT_ROOT = Path(
    os.getenv("PROJECT_ROOT", "/app")
).resolve()

INVENTORY_FILE = Path(
    os.getenv(
        "ANSIBLE_INVENTORY",
        "/app/inventory/hosts.yml"
    )
).resolve()

PLAYBOOK_FILE = Path(
    os.getenv(
        "ANSIBLE_PLAYBOOK",
        "/app/ansible/site.yml"
    )
).resolve()

STAGING_SCRIPT = Path(
    os.getenv(
        "STAGING_SCRIPT",
        "/app/scripts/stage_pos_xmls.py"
    )
).resolve()

INCOMING_DIRECTORY = Path(
    os.getenv(
        "INCOMING_DIRECTORY",
        "/app/incoming/new"
    )
).resolve()

LOG_DIRECTORY = Path(
    os.getenv(
        "LOG_DIRECTORY",
        "/app/logs"
    )
).resolve()

API_TOKEN = os.getenv("RUNNER_API_TOKEN", "").strip()
DISABLE_API_AUTH = os.getenv("DISABLE_API_AUTH", "false").lower() == "true".strip()

LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)


class RunRequest(BaseModel):
    limit: str = Field(
        ...,
        min_length=1,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:-]+$"
    )

    run_staging: bool = True


def execute_command(command: list[str]) -> dict:
    result = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=1800,
        check=False,
        env={
            **os.environ,
            "ANSIBLE_HOST_KEY_CHECKING": os.getenv(
                "ANSIBLE_HOST_KEY_CHECKING",
                "True"
            )
        }
    )

    return {
        "command": command,
        "return_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr
    }


def validate_required_files():
    missing = []

    for path in [
        INVENTORY_FILE,
        PLAYBOOK_FILE
    ]:
        if not path.exists():
            missing.append(str(path))

    if missing:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Required Ansible files are missing",
                "files": missing
            }
        )


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "inventory_exists": INVENTORY_FILE.exists(),
        "playbook_exists": PLAYBOOK_FILE.exists(),
        "staging_script_exists": STAGING_SCRIPT.exists()
    }


@app.post("/run")
def run_playbook(
    request: RunRequest,
    authorization: str | None = Header(default=None),
):
    if API_TOKEN:
        expected_token = f"Bearer {API_TOKEN}"

        if authorization != expected_token:
            raise HTTPException(
                status_code=401,
                detail="Invalid API token",
            )

    validate_required_files()

    execution_id = str(uuid.uuid4())
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    execution_log = {
        "execution_id": execution_id,
        "limit": request.limit,
        "started_at": timestamp,
        "staging": None,
        "ansible": None
    }

    if request.run_staging:
        if not STAGING_SCRIPT.exists():
            raise HTTPException(
                status_code=500,
                detail=f"Staging script not found: {STAGING_SCRIPT}"
            )

        staging_command = [
            "python3",
            str(STAGING_SCRIPT),
            "--source",
            str(INCOMING_DIRECTORY)
        ]

        staging_result = execute_command(staging_command)
        execution_log["staging"] = staging_result

        if staging_result["return_code"] != 0:
            return {
                "status": "failed",
                "stage": "staging",
                **execution_log
            }

    ansible_command = [
        "ansible-playbook",
        "-i",
        str(INVENTORY_FILE),
        str(PLAYBOOK_FILE),
        "--limit",
        request.limit
    ]

    ansible_result = execute_command(ansible_command)
    execution_log["ansible"] = ansible_result

    log_file = LOG_DIRECTORY / (
        f"execution-{timestamp}-{execution_id}.log"
    )

    log_file.write_text(
        f"Execution ID: {execution_id}\n"
        f"Limit: {request.limit}\n"
        f"Return code: {ansible_result['return_code']}\n\n"
        f"STDOUT\n"
        f"======\n"
        f"{ansible_result['stdout']}\n\n"
        f"STDERR\n"
        f"======\n"
        f"{ansible_result['stderr']}\n",
        encoding="utf-8"
    )

    status = (
        "success"
        if ansible_result["return_code"] == 0
        else "failed"
    )

    return {
        "status": status,
        "log_file": str(log_file),
        **execution_log
    }
