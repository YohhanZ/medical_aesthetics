#!/usr/bin/env bash
# Read-only allocation metadata; no file contents or cleanup operations.
set -u
printf '== filesystem usage ==\n'
df -B1 -T /
df -ih /
printf '\n== Docker summary ==\n'
timeout 45s nice -n 19 docker system df
printf '\n== system journal ==\n'
journalctl --disk-usage 2>/dev/null || true
printf '\n== root directory allocation (same filesystem only) ==\n'
if sudo -n true 2>/dev/null; then
    sudo -n timeout 45s nice -n 19 ionice -c 3 du -x -B1 --max-depth=1 / 2>/dev/null | sort -n
    printf '\n== running container writable-layer sizes ==\n'
    timeout 30s nice -n 19 docker ps --size --format 'table {{.Names}}\t{{.Size}}'
else
    printf 'Passwordless sudo unavailable; no privilege change attempted.\n'
fi
