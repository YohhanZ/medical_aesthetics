#!/usr/bin/env bash
# Pause only the named existing project. Every data volume/image remains intact.
set -eu
cd /home/ubuntu/medical-aesthetics-demo
umask 077
compose=(docker compose --env-file runtime/compose.env -f compose.yml)
"${compose[@]}" config --quiet
for image in medical-aesthetics-api:demo-20261013-r2 medical-consultation-sandbox:demo-20261013-r2 medical-aesthetics-web:demo-20261013-r2 pgvector/pgvector:0.8.2-pg17 neo4j:5.26 milvusdb/milvus:v2.5.27; do
    docker image inspect --format '{{.Id}}' "$image" >/dev/null
done
docker run --rm --network=none --memory=64m --pids-limit=16 --entrypoint nginx --add-host api:127.0.0.1 --mount type=bind,source=/home/ubuntu/medical-aesthetics-demo/runtime/letsencrypt,target=/etc/letsencrypt,readonly medical-aesthetics-web:demo-20261013-r2 -t
python3 - <<'SAVE'
import json, subprocess
from pathlib import Path
names = ['mapmost-web', 'mapmost-backend', 'mapmost-milvus', 'mapmost-mysql', 'mapmost-etcd', 'mapmost-minio']
fmt = '{"id":{{json .Id}},"name":{{json .Name}},"state":{{json .State.Status}},"project":{{json (index .Config.Labels "com.docker.compose.project")}},"restart":{{json .HostConfig.RestartPolicy.Name}}}'
rows = [json.loads(subprocess.check_output(['docker', 'inspect', '--format', fmt, name])) for name in names]
assert all(row['project'] == 'mapmost-rag' and row['state'] == 'running' for row in rows)
with Path('runtime/previous-project.json').open('x') as out:
    json.dump(rows, out, indent=2)
print('Saved exact identities and restart policies for six existing project containers.')
SAVE
docker stop --time 30 mapmost-web mapmost-backend
docker stop --time 30 mapmost-milvus mapmost-mysql mapmost-minio mapmost-etcd
printf '\n== memory after pause ==\n'
free -m
if ! "${compose[@]}" up -d --wait --wait-timeout 300 postgres neo4j etcd minio milvus; then
    "${compose[@]}" stop
    docker start mapmost-etcd mapmost-minio mapmost-mysql mapmost-milvus mapmost-backend mapmost-web
    printf 'New storage startup failed; original project restarted, all volumes preserved.\n'
    exit 1
fi
printf '\nNew isolated storage healthy. Original containers stopped; no volumes/images deleted.\n'
