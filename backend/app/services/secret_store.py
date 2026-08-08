from __future__ import annotations

import ctypes
import json
import os
from ctypes import wintypes
from pathlib import Path
from typing import Protocol


class SecretProtector(Protocol):
    def protect(self, value: bytes) -> bytes: ...

    def unprotect(self, value: bytes) -> bytes: ...


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_byte)),
    ]


class WindowsDpapiProtector:
    _UI_FORBIDDEN = 0x1

    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("Windows DPAPI is only available on Windows")
        self._crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._crypt32.CryptProtectData.restype = wintypes.BOOL
        self._crypt32.CryptUnprotectData.restype = wintypes.BOOL
        self._kernel32.LocalFree.restype = ctypes.c_void_p

    def protect(self, value: bytes) -> bytes:
        return self._transform("CryptProtectData", value)

    def unprotect(self, value: bytes) -> bytes:
        return self._transform("CryptUnprotectData", value)

    def _transform(self, function_name: str, value: bytes) -> bytes:
        source_buffer = ctypes.create_string_buffer(value)
        source = _DataBlob(
            len(value), ctypes.cast(source_buffer, ctypes.POINTER(ctypes.c_byte))
        )
        destination = _DataBlob()
        function = getattr(self._crypt32, function_name)
        if function_name == "CryptProtectData":
            succeeded = function(
                ctypes.byref(source),
                "Market Pilot local integration config",
                None,
                None,
                None,
                self._UI_FORBIDDEN,
                ctypes.byref(destination),
            )
        else:
            succeeded = function(
                ctypes.byref(source),
                None,
                None,
                None,
                None,
                self._UI_FORBIDDEN,
                ctypes.byref(destination),
            )
        if not succeeded:
            raise OSError(ctypes.get_last_error(), "Windows DPAPI operation failed")
        try:
            return ctypes.string_at(destination.pbData, destination.cbData)
        finally:
            self._kernel32.LocalFree(destination.pbData)


class EncryptedSecretStore:
    def __init__(self, path: Path, protector: SecretProtector) -> None:
        self.path = path
        self._protector = protector

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        decoded = self._protector.unprotect(self.path.read_bytes())
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("encrypted integration config is not an object")
        return {
            str(key): str(value)
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str)
        }

    def save(self, values: dict[str, str]) -> None:
        if not values:
            self.path.unlink(missing_ok=True)
            return
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
        encrypted = self._protector.protect(payload)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary_path.write_bytes(encrypted)
        os.replace(temporary_path, self.path)
