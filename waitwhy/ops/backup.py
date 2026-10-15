"""Database backups: pg_dump custom format, gzip-free (already compressed), optional upload to S3 storage,
local retention of the newest N files. Restore with scripts/restore.sh."""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.engine import make_url

from waitwhy.settings import secrets


def run_backup(keep: int = 14) -> dict:
    s = secrets()
    url = make_url(s.database_url)
    out_dir = Path(s.backup_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = out_dir / f"waitwhy-{stamp}.dump"
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    cmd = ["pg_dump", "-Fc", "-h", url.host or "localhost", "-p", str(url.port or 5432), "-U", url.username or "postgres",
           "-f", str(path), url.database]
    subprocess.run(cmd, check=True, env=env, timeout=1800)
    uploaded = None
    if s.s3_bucket:
        from waitwhy.providers.registry import _storage
        uploaded = _storage("s3").put_file(path, f"backups/{path.name}")
    dumps = sorted(out_dir.glob("waitwhy-*.dump"))
    for old in dumps[:-keep]:
        old.unlink()
    return {"file": str(path), "bytes": path.stat().st_size, "uploaded": uploaded}
