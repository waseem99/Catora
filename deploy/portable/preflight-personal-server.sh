#!/usr/bin/env bash
set -euo pipefail

failures=0
warnings=0

pass() { printf 'PASS: %s\n' "$1"; }
warn() { printf 'WARN: %s\n' "$1"; warnings=$((warnings + 1)); }
fail() { printf 'FAIL: %s\n' "$1"; failures=$((failures + 1)); }

arch="$(uname -m)"
if [[ "$arch" == "x86_64" || "$arch" == "amd64" ]]; then
  pass "architecture is $arch (matches the currently certified GHCR images)"
else
  fail "architecture is $arch; the currently certified images were built on linux/amd64 and must not be substituted with an untested rebuild"
fi

for command in docker git curl python3; do
  if command -v "$command" >/dev/null 2>&1; then
    pass "$command is installed"
  else
    fail "$command is required"
  fi
done

if command -v docker >/dev/null 2>&1; then
  if docker compose version >/dev/null 2>&1; then
    pass "Docker Compose v2 is available"
  else
    fail "Docker Compose v2 is required (docker compose ...)"
  fi
  if docker info >/dev/null 2>&1; then
    pass "current user can talk to the Docker daemon"
  else
    fail "current user cannot talk to the Docker daemon"
  fi
fi

if [[ -r /proc/meminfo ]]; then
  mem_kib="$(awk '/MemTotal:/ {print $2}' /proc/meminfo)"
  if (( mem_kib >= 7 * 1024 * 1024 )); then
    pass "RAM is approximately $((mem_kib / 1024 / 1024)) GiB"
  else
    warn "RAM is approximately $((mem_kib / 1024 / 1024)) GiB; 8 GiB is recommended for the all-in-one production stack"
  fi
fi

available_kib="$(df -Pk . | awk 'NR==2 {print $4}')"
if (( available_kib >= 30 * 1024 * 1024 )); then
  pass "at least 30 GiB disk is currently free"
else
  warn "less than 30 GiB disk is currently free; database, images, MinIO objects and backups need headroom"
fi

if command -v ss >/dev/null 2>&1; then
  for port in 80 443; do
    if ss -ltnH "sport = :$port" 2>/dev/null | grep -q .; then
      fail "TCP port $port is already in use; the bundled Caddy edge needs it or must be adapted to the existing reverse proxy"
    else
      pass "TCP port $port is available"
    fi
  done
else
  warn "ss is unavailable; could not check whether ports 80/443 are free"
fi

printf '\nPreflight summary: %d failure(s), %d warning(s).\n' "$failures" "$warnings"
if (( failures > 0 )); then
  exit 1
fi
