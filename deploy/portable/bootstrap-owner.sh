#!/usr/bin/env bash
set -euo pipefail

API_URL="${CATORA_BOOTSTRAP_API_URL:-http://127.0.0.1:8000}"

read -r -p "Organization name [Catora]: " organization_name
organization_name="${organization_name:-Catora}"
read -r -p "Organization slug [catora]: " organization_slug
organization_slug="${organization_slug:-catora}"
read -r -p "Workspace name [Production]: " workspace_name
workspace_name="${workspace_name:-Production}"
read -r -p "Workspace slug [production]: " workspace_slug
workspace_slug="${workspace_slug:-production}"
read -r -p "Owner email: " owner_email
read -r -p "Owner display name: " owner_display_name
read -r -s -p "Owner password (12+ characters): " owner_password
printf '\n'
read -r -s -p "Confirm owner password: " owner_password_confirm
printf '\n'

if [[ -z "$owner_email" || -z "$owner_display_name" ]]; then
  echo "Owner email and display name are required." >&2
  exit 1
fi
if [[ ${#owner_password} -lt 12 ]]; then
  echo "Password must be at least 12 characters." >&2
  exit 1
fi
if [[ "$owner_password" != "$owner_password_confirm" ]]; then
  echo "Passwords do not match." >&2
  exit 1
fi

payload="$({
  ORGANIZATION_NAME="$organization_name" \
  ORGANIZATION_SLUG="$organization_slug" \
  WORKSPACE_NAME="$workspace_name" \
  WORKSPACE_SLUG="$workspace_slug" \
  OWNER_EMAIL="$owner_email" \
  OWNER_DISPLAY_NAME="$owner_display_name" \
  OWNER_PASSWORD="$owner_password" \
  python3 - <<'PY'
import json
import os

print(json.dumps({
    "organization_name": os.environ["ORGANIZATION_NAME"],
    "organization_slug": os.environ["ORGANIZATION_SLUG"],
    "workspace_name": os.environ["WORKSPACE_NAME"],
    "workspace_slug": os.environ["WORKSPACE_SLUG"],
    "email": os.environ["OWNER_EMAIL"],
    "display_name": os.environ["OWNER_DISPLAY_NAME"],
    "password": os.environ["OWNER_PASSWORD"],
}))
PY
})"

unset owner_password owner_password_confirm

curl --fail-with-body --silent --show-error \
  -X POST \
  -H 'Content-Type: application/json' \
  --data-binary "$payload" \
  "${API_URL%/}/api/v1/auth/bootstrap" \
  >/dev/null

unset payload

echo "Production owner bootstrap succeeded."
echo "Sign in through https://catora.codistan.org after DNS/TLS are active."
