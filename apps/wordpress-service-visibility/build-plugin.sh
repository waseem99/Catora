#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "$0")" && pwd)
out=${1:-"$root/build/catora-service-visibility.zip"}
mkdir -p "$(dirname "$out")"
out=$(cd "$(dirname "$out")" && pwd)/$(basename "$out")
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
plugin_dir="$stage/catora-service-visibility"
mkdir -p "$plugin_dir/includes"
cp "$root/catora-service-visibility.php" "$plugin_dir/"
cp "$root/uninstall.php" "$plugin_dir/"
cp "$root/readme.txt" "$plugin_dir/"
cp "$root/README.md" "$plugin_dir/"
cp "$root/includes/class-catora-service-visibility.php" "$plugin_dir/includes/"
rm -f "$out"
(
  cd "$stage"
  zip -qr "$out" catora-service-visibility
)
printf '%s\n' "$out"
