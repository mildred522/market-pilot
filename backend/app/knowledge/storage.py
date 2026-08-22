from __future__ import annotations

import hashlib
import ipaddress
import mimetypes
import socket
from collections.abc import Callable
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx

from app.knowledge.document import AcquiredDocument
from app.knowledge.manifest import KnowledgeManifestEntry


class KnowledgeAcquisitionError(ValueError):
    pass


_PROXY_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


class KnowledgeStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def store_raw(
        self,
        *,
        source_key: str,
        document: AcquiredDocument,
    ) -> str:
        suffix = _safe_suffix(document.filename, document.media_type)
        relative = Path("raw") / source_key / f"{document.sha256}{suffix}"
        target = self.resolve(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if _sha256(target.read_bytes()) != document.sha256:
                raise KnowledgeAcquisitionError("stored document hash mismatch")
        else:
            target.write_bytes(document.content)
        return relative.as_posix()

    def resolve(self, relative: str | Path) -> Path:
        value = Path(relative)
        if value.is_absolute():
            raise KnowledgeAcquisitionError("knowledge storage path must be relative")
        target = (self.root / value).resolve()
        if not target.is_relative_to(self.root):
            raise KnowledgeAcquisitionError("knowledge storage path escapes its root")
        return target


class SecureDocumentLoader:
    def __init__(
        self,
        *,
        max_bytes: int = 25 * 1024 * 1024,
        timeout_seconds: float = 20,
        dns_resolver: Callable[..., list[tuple]] = socket.getaddrinfo,
        allow_proxy_fake_ip: bool = False,
    ) -> None:
        self._max_bytes = max_bytes
        self._timeout_seconds = timeout_seconds
        self._dns_resolver = dns_resolver
        self._allow_proxy_fake_ip = allow_proxy_fake_ip

    def acquire(
        self,
        entry: KnowledgeManifestEntry,
        *,
        manifest_directory: Path,
    ) -> AcquiredDocument:
        acquisition = entry.acquisition
        if acquisition.local_path is not None:
            content, media_type, filename = self._read_local(
                acquisition.local_path,
                manifest_directory,
            )
        elif acquisition.url is not None:
            content, media_type, filename = self._download(str(acquisition.url))
        else:
            raise KnowledgeAcquisitionError("document location is missing")

        normalized_media_type = media_type.split(";", 1)[0].strip().lower()
        if normalized_media_type not in acquisition.allowed_media_types:
            raise KnowledgeAcquisitionError(
                f"media type is not allowed: {normalized_media_type}"
            )
        digest = _sha256(content)
        if (
            acquisition.expected_sha256 is not None
            and digest != acquisition.expected_sha256.lower()
        ):
            raise KnowledgeAcquisitionError("downloaded document hash mismatch")
        return AcquiredDocument(
            content=content,
            media_type=normalized_media_type,
            filename=filename,
            sha256=digest,
        )

    def _read_local(
        self,
        relative_path: str,
        manifest_directory: Path,
    ) -> tuple[bytes, str, str]:
        root = manifest_directory.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise KnowledgeAcquisitionError("local document escapes manifest directory")
        if not path.is_file():
            raise KnowledgeAcquisitionError(
                f"local document does not exist: {relative_path}"
            )
        if path.stat().st_size > self._max_bytes:
            raise KnowledgeAcquisitionError("local document exceeds size limit")
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return path.read_bytes(), media_type, path.name

    def _download(self, url: str) -> tuple[bytes, str, str]:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise KnowledgeAcquisitionError("only public HTTP(S) URLs are allowed")
        self._verify_public_host(parsed.hostname, parsed.port)
        with httpx.Client(
            timeout=self._timeout_seconds,
            follow_redirects=False,
        ) as client:
            with client.stream("GET", url) as response:
                if 300 <= response.status_code < 400:
                    raise KnowledgeAcquisitionError("redirects require manifest review")
                response.raise_for_status()
                declared_size = int(response.headers.get("content-length", "0") or 0)
                if declared_size > self._max_bytes:
                    raise KnowledgeAcquisitionError(
                        "remote document exceeds size limit"
                    )
                content = bytearray()
                for block in response.iter_bytes():
                    content.extend(block)
                    if len(content) > self._max_bytes:
                        raise KnowledgeAcquisitionError(
                            "remote document exceeds size limit"
                        )
                media_type = response.headers.get(
                    "content-type", "application/octet-stream"
                )
        filename = Path(unquote(parsed.path)).name or "document"
        return bytes(content), media_type, filename

    def _verify_public_host(self, hostname: str, port: int | None) -> None:
        normalized = hostname.rstrip(".").lower()
        if normalized == "localhost" or normalized.endswith(".local"):
            raise KnowledgeAcquisitionError("private hosts are not allowed")
        try:
            addresses = self._dns_resolver(normalized, port or 443)
        except OSError as error:
            raise KnowledgeAcquisitionError(
                "document host cannot be resolved"
            ) from error
        if not addresses:
            raise KnowledgeAcquisitionError("document host has no addresses")
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if self._allow_proxy_fake_ip and ip in _PROXY_FAKE_IP_NETWORK:
                continue
            if not ip.is_global:
                raise KnowledgeAcquisitionError(
                    "private network addresses are not allowed"
                )


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_suffix(filename: str, media_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix and len(suffix) <= 10 and suffix[1:].isalnum():
        return suffix
    return mimetypes.guess_extension(media_type) or ".bin"
