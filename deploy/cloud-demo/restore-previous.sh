#!/usr/bin/env bash
set -eu
cd /home/ubuntu/medical-aesthetics-demo
python3 - <<'CHECK'
import json, subprocess
from pathlib import Path
rows = json.loads(Path('runtime/previous-project.json').read_text())
for row in rows:
    current = subprocess.check_output(['docker', 'inspect', '--format', '{{.Id}}', row['name'].lstrip('/')]).decode().strip()
    assert current == row['id'], 'Original container identity changed; stop for manual review'
CHECK
docker compose --env-file runtime/compose.env -f compose.yml --profile tls stop
docker start mapmost-etcd mapmost-minio mapmost-mysql mapmost-milvus mapmost-backend mapmost-web
printf 'Original project restart requested. Recheck health before declaring restoration complete.\n'
