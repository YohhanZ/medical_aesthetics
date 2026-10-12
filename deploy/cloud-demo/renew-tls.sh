#!/usr/bin/env bash
set -eu
cd /home/ubuntu/medical-aesthetics-demo
exec 9>runtime/tls-renew.lock
flock -n 9 || exit 0
# A paused deployment cannot answer HTTP-01 challenges; resume web before renewal.
if [ -z "$(docker compose --env-file runtime/compose.env -f compose.yml ps -q web)" ]; then
    exit 0
fi
docker compose --env-file runtime/compose.env -f compose.yml --profile tls run --rm --interactive=false certbot renew --quiet --cert-name 43.142.39.108
docker compose --env-file runtime/compose.env -f compose.yml exec -T web nginx -t </dev/null
docker compose --env-file runtime/compose.env -f compose.yml exec -T web nginx -s reload </dev/null
