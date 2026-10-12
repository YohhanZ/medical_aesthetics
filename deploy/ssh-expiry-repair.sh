#!/usr/bin/env bash
# Repair only the exact demo key entry; retain its original UTC expiry instant.
set -eu
[ "$(id -un)" = ubuntu ] || { printf 'Please run as ubuntu.\n'; exit 1; }
file="$HOME/.ssh/authorized_keys"
[ -f "$file" ] && [ ! -L "$file" ] || { printf 'Expected a regular authorized_keys file.\n'; exit 1; }
pub='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPqB4aEXsEmtN7rJ32YDQxeA7WnIvCZrke8W/A6gK2Al medical-aesthetics-demo-2026-10-13'
old="restrict,expiry-time=\"20261015172852Z\" $pub"
expires=$(env -u TZ date -d '2026-10-15 17:28:52 UTC' +%Y%m%d%H%M%S)
new="restrict,expiry-time=\"$expires\" $pub"
if grep -Fxq -- "$new" "$file"; then
    printf 'Already corrected: %s\n' "$expires"
    exit 0
fi
[ "$(grep -Fxc -- "$old" "$file" || true)" = 1 ] || { printf 'Expected exactly one original project entry; no changes made.\n'; exit 1; }
backup="$file.before-expiry-$(date -u +%Y%m%dT%H%M%S%N)"
cp -p -- "$file" "$backup"
sed -i "\|^${old}$|s|expiry-time=\"20261015172852Z\"|expiry-time=\"$expires\"|" "$file"
grep -Fxq -- "$new" "$file"
printf 'Corrected expiry: %s (server local time); UTC instant unchanged.\nBackup: %s\n' "$expires" "$backup"
