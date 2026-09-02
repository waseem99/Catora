#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$HERE/.env.personal-server.example"
TARGET="$HERE/.env.production"

if [[ -e "$TARGET" ]]; then
  echo "$TARGET already exists; refusing to overwrite production secrets." >&2
  exit 1
fi

TEMPLATE="$TEMPLATE" TARGET="$TARGET" python3 - <<'PY'
from __future__ import annotations

import base64
import os
import secrets
import string
from pathlib import Path


def alnum(length: int) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def encryption_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


template = Path(os.environ["TEMPLATE"])
target = Path(os.environ["TARGET"])
text = template.read_text(encoding="utf-8")
replacements = {
    "CHANGE_ME_32_PLUS_RANDOM_CHARACTERS": secrets.token_urlsafe(48),
    "CHANGE_ME_URL_SAFE_RANDOM_PASSWORD": alnum(48),
    "CHANGE_ME_RANDOM_ACCESS_KEY": alnum(24),
    "CHANGE_ME_RANDOM_SECRET_KEY": alnum(64),
    "CHANGE_ME_URLSAFE_BASE64_32_BYTE_KEY": encryption_key(),
}
for marker, value in replacements.items():
    if marker not in text:
        raise SystemExit(f"Template is missing required marker: {marker}")
    text = text.replace(marker, value)

fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w", encoding="utf-8") as handle:
    handle.write(text)
PY

chmod 600 "$TARGET"
echo "Created protected production environment: $TARGET"
echo "Secrets were generated without printing them. Back this file up through a secure secret channel."
