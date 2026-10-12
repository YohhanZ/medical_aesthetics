"""Run integration checks against the explicitly isolated local test database."""

import os
import subprocess
import sys

from psycopg.conninfo import make_conninfo

from app.config import Settings

dsn = Settings().database_url
os.environ["MA_TEST_DATABASE_URL"] = make_conninfo(dsn, dbname="ma_m1_test")
raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", "-q", *sys.argv[1:]]))
