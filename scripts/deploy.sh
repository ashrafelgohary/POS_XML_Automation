#!/usr/bin/env bash
set -euo pipefail

# Stage any newly dropped XMLs
if [ -d "incoming/new" ] && ls incoming/new/*.xml >/dev/null 2>&1; then
  echo "[Stage] Found new XMLs, staging..."
  python3 scripts/stage_pos_xmls.py --source incoming/new
else
  echo "[Stage] No new XMLs to stage."
fi

# Optional: limit targets: ./scripts/deploy.sh --limit "pos-001,pos-002"
extra=()
if [ "${1:-}" = "--limit" ] && [ -n "${2:-}" ]; then
  extra=( --limit "$2" )
fi

echo "[Deploy] Running Ansible..."
ansible-playbook -i inventory/hosts.yml ansible/site.yml "${extra[@]}"

