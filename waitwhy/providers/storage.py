"""Object storage: local filesystem (dev / single server) or any S3-compatible service
(AWS S3, Cloudflare R2, Backblaze B2, MinIO). Binary media never goes into Postgres."""
from __future__ import annotations

import shutil
from pathlib import Path


class LocalStorage:
    def __init__(self, root: str, public_base_url: str | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.public_base_url = public_base_url

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if not str(p).startswith(str(self.root.resolve())):
            raise ValueError("invalid storage key")
        return p

    def put_file(self, local: Path, key: str, content_type: str | None = None) -> str:
        dst = self._p(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if Path(local).resolve() != dst:
            shutil.copyfile(local, dst)
        return key

    def get_file(self, key: str, local: Path) -> Path:
        shutil.copyfile(self._p(key), local)
        return local

    def local_path(self, key: str) -> Path | None:
        return self._p(key)

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def public_url(self, key: str, expires_s: int = 3600) -> str | None:
        # Platforms like Instagram must PULL the video from a public HTTPS URL. Local storage can only
        # offer that if the server is reachable publicly (PUBLIC_BASE_URL) - otherwise use S3.
        return f"{self.public_base_url.rstrip('/')}/public-media/{key}" if self.public_base_url else None

    def health(self) -> bool:
        probe = self.root / ".health"
        probe.write_text("ok")
        return probe.read_text() == "ok"


class S3Storage:
    def __init__(self, bucket: str, endpoint_url: str | None, region: str, key_id: str, secret: str,
                 public_base_url: str | None = None):
        import boto3

        self.bucket = bucket
        self.public_base_url = public_base_url
        self.s3 = boto3.client("s3", endpoint_url=endpoint_url or None, region_name=region,
                               aws_access_key_id=key_id or None, aws_secret_access_key=secret or None)
        self.cache = Path("/tmp/waitwhy-s3-cache")
        self.cache.mkdir(parents=True, exist_ok=True)

    def put_file(self, local: Path, key: str, content_type: str | None = None) -> str:
        extra = {"ContentType": content_type} if content_type else {}
        self.s3.upload_file(str(local), self.bucket, key, ExtraArgs=extra)
        return key

    def get_file(self, key: str, local: Path) -> Path:
        self.s3.download_file(self.bucket, key, str(local))
        return local

    def local_path(self, key: str) -> Path | None:
        p = self.cache / key
        if not p.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
            self.get_file(key, p)
        return p

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:  # noqa: BLE001
            return False

    def public_url(self, key: str, expires_s: int = 3600) -> str | None:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{key}"
        return self.s3.generate_presigned_url("get_object", Params={"Bucket": self.bucket, "Key": key},
                                              ExpiresIn=expires_s)

    def health(self) -> bool:
        self.s3.head_bucket(Bucket=self.bucket)
        return True
