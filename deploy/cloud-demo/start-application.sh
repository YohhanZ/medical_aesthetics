#!/usr/bin/env bash
set -eu
cd /home/ubuntu/medical-aesthetics-demo
compose=(docker compose --env-file runtime/compose.env -f compose.yml)
if ! "${compose[@]}" --profile setup run --rm --interactive=false bootstrap; then
    bash restore-previous.sh
    exit 1
fi
if ! "${compose[@]}" up -d --wait --wait-timeout 180 api worker marketing-worker; then
    bash restore-previous.sh
    exit 1
fi
"${compose[@]}" --profile tls stop challenge
if ! "${compose[@]}" up -d web; then
    bash restore-previous.sh
    exit 1
fi
printf 'Application started. Knowledge projection and HTTPS acceptance still require verification.\n'
