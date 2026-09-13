"""Private storage abstraction. Files never live beneath a publicly served directory."""

import os
from pathlib import Path
from typing import Protocol
from uuid import UUID

from larimia.config import get_settings


class Storage(Protocol):
    def put(self, key: str, content: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...


class LocalStorage:
    def path(self, key: str) -> Path:
        UUID(key)  # Only server-generated object identifiers, never client paths.
        root = Path(get_settings().storage_root)
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        return root / key

    def put(self, key: str, content: bytes) -> None:
        path = self.path(key)
        try:
            with os.fdopen(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600), "wb") as f:
                f.write(content)
        except FileExistsError:
            if path.read_bytes() != content:
                raise ValueError("Object content is immutable") from None

    def get(self, key: str) -> bytes:
        return self.path(key).read_bytes()


class AzureBlobStorage:
    def client(self):
        from azure.identity import DefaultAzureCredential
        from azure.storage.blob import BlobServiceClient

        settings = get_settings()
        credential = DefaultAzureCredential(
            managed_identity_client_id=settings.azure_client_id or None
        )
        return credential, BlobServiceClient(
            settings.azure_storage_url, credential=credential, connection_timeout=5, read_timeout=10
        )

    def put(self, key: str, content: bytes) -> None:
        import hashlib

        from azure.core.exceptions import ResourceExistsError

        UUID(key)
        credential, client = self.client()
        with credential, client:
            blob = client.get_blob_client(get_settings().azure_storage_container, key)
            digest = hashlib.sha256(content).hexdigest()
            try:
                blob.upload_blob(content, overwrite=False, metadata={"sha256": digest})
            except ResourceExistsError:
                if blob.get_blob_properties().metadata.get("sha256") != digest:
                    raise ValueError("Immutable storage key has different contents") from None

    def get(self, key: str) -> bytes:
        UUID(key)
        credential, client = self.client()
        with credential, client:
            return (
                client.get_blob_client(get_settings().azure_storage_container, key)
                .download_blob()
                .readall()
            )


def storage() -> Storage:
    return AzureBlobStorage() if get_settings().storage_mode == "azure" else LocalStorage()
