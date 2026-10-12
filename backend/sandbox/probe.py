"""Separate acceptance-only image; never a mode or endpoint in the consultation worker."""

import errno
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

job = json.loads(sys.stdin.readline())
mode = job["probe"]
if mode == "hang":
    time.sleep(120)
elif mode == "oom":
    blocks = []
    while True:
        blocks.append(bytearray(16 * 1024 * 1024))
elif mode == "malformed":
    print("invalid-json", flush=True)
elif mode == "oversize":
    print("x" * (3 * 1024 * 1024), flush=True)
elif mode == "operation":
    print(
        json.dumps({"kind": "call", "seq": 1, "op": "shell.exec", "payload": {"command": "id"}}),
        flush=True,
    )
    response = json.loads(sys.stdin.readline())
    print(json.dumps({"kind": "done", "denied": response.get("error", {}).get("code")}), flush=True)
elif mode == "boundaries":
    status = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    checks = {
        "nonroot": os.getuid() == 65532,
        "capabilities_dropped": int(status["CapEff"].strip(), 16) == 0,
        "no_new_privileges": status["NoNewPrivs"].strip() == "1",
        "seccomp": status["Seccomp"].strip() == "2",
        "memory_limit": Path("/sys/fs/cgroup/memory.max").read_text().strip() == "536870912",
        "cpu_limit": Path("/sys/fs/cgroup/cpu.max").read_text().strip() == "100000 100000",
        "pids_limit": Path("/sys/fs/cgroup/pids.max").read_text().strip() == "64",
        "only_loopback": sorted(p.name for p in Path("/sys/class/net").iterdir()) == ["lo"],
        "no_socket_mount": not Path("/var/run/docker.sock").exists(),
        "no_dotenv": not Path("/worker/.env").exists(),
        "no_host_workspace": not Path("/worker/runtime").exists(),
        "no_credentials": not any(k.startswith(("MA_", "LLM_")) for k in os.environ),
    }
    try:
        Path("/worker/denied-probe").write_text("synthetic")
        checks["root_readonly"] = False
    except OSError as error:
        checks["root_readonly"] = error.errno == errno.EROFS
    try:
        with socket.create_connection(("198.51.100.1", 443), timeout=0.3):
            checks["network_denied"] = False
    except OSError:
        checks["network_denied"] = True
    tmp = Path("/tmp/probe")
    tmp.write_text("#!/bin/sh\nexit 0\n")
    tmp.chmod(0o700)
    try:
        subprocess.run([str(tmp)], check=True)
        checks["tmp_noexec"] = False
    except OSError as error:
        checks["tmp_noexec"] = error.errno == errno.EACCES
    children = []
    try:
        for _ in range(100):
            children.append(subprocess.Popen([sys.executable, "-c", "import time;time.sleep(5)"]))
        checks["pids_enforced"] = False
    except OSError as error:
        checks["pids_enforced"] = error.errno == errno.EAGAIN
    finally:
        for child in children:
            child.kill()
            child.wait()
    print(json.dumps({"kind": "done", "checks": checks}), flush=True)
else:
    raise SystemExit(1)
