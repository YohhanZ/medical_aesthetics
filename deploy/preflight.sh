#!/usr/bin/env bash
# Read-only inventory; no installs, restarts, configuration reads, credentials or business data.
set -u

printf '== identity and OS ==\n'
id -un
if [ -r /etc/os-release ]; then
    awk -F= '/^(PRETTY_NAME|ID|VERSION_ID)=/ { print }' /etc/os-release
fi
printf '\n== CPU ==\n'
getconf _NPROCESSORS_ONLN
if command -v lscpu >/dev/null 2>&1; then
    lscpu | awk '/^Architecture:|^CPU\(s\):|^Model name:|^Flags:/ { print }'
fi
printf '\n== memory ==\n'
free -m
printf '\n== disk ==\n'
df -h / /var/lib/docker 2>/dev/null || df -h /
printf '\n== listening TCP ports ==\n'
ss -ltn 2>/dev/null || true
printf '\n== largest process memory (no command arguments) ==\n'
ps -eo comm,rss --sort=-rss | head -n 12
printf '\n== Docker access ==\n'
if command -v docker >/dev/null 2>&1; then
    docker --version
    docker compose version 2>/dev/null || true
    if docker info --format '{{.ServerVersion}}' 2>/dev/null; then
        docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
        docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}\t{{.PIDs}}'
    else
        printf 'Docker daemon inaccessible to this account; no permission changes attempted.\n'
    fi
else
    printf 'Docker CLI not installed; no installation attempted.\n'
fi
