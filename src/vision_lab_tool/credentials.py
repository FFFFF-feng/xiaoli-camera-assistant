"""Local-only credential vault, encrypted for the current Windows user with DPAPI."""

from __future__ import annotations

import base64
import ctypes
import json
import os
import tempfile
from ctypes import wintypes
from pathlib import Path

KEY_NAMES = ("DASHSCOPE_API_KEY", "ARK_API_KEY", "ZHIPU_API_KEY")


class _Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data):
    buffer = ctypes.create_string_buffer(data)
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))), buffer


def _crypt(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise OSError("本机密钥加密保存需要 Windows；其他系统可使用环境变量或 secrets。")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    source, source_buffer = _blob(data)
    entropy, entropy_buffer = _blob(b"xiaoli-vision-lab-credentials-v1")
    output = _Blob()
    method = crypt32.CryptUnprotectData if decrypt else crypt32.CryptProtectData
    description_type = ctypes.POINTER(wintypes.LPWSTR) if decrypt else wintypes.LPCWSTR
    method.argtypes = [
        ctypes.POINTER(_Blob),
        description_type,
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    method.restype = wintypes.BOOL
    # Do not set CRYPTPROTECT_LOCAL_MACHINE: ciphertext is bound to this Windows user.
    succeeded = method(
        ctypes.byref(source),
        None if decrypt else "Xiaoli Vision Lab",
        ctypes.byref(entropy),
        None,
        None,
        1,
        ctypes.byref(output),
    )
    if not succeeded:
        raise OSError(f"Windows 当前账号无法处理本机密钥（错误码 {ctypes.get_last_error()}）。")
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel32.LocalFree(ctypes.cast(output.data, ctypes.c_void_p))
        # Keep the input buffers alive until the native call has completed.
        del source_buffer, entropy_buffer


def _validate(values):
    if not isinstance(values, dict) or any(k not in KEY_NAMES for k in values):
        raise ValueError("本机密钥包含不支持的服务商。")
    for value in values.values():
        if not isinstance(value, str) or "\n" in value or "\r" in value or len(value) > 8192:
            raise ValueError("API Key 必须为单行文本，长度不超过 8192 字符。")


class KeyVault:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            if self.path.stat().st_size > 128_000:
                raise ValueError("invalid size")
            envelope = json.loads(self.path.read_text("utf-8"))
            if envelope.get("format") != "windows-dpapi-v1":
                raise ValueError("invalid format")
            clear = _crypt(base64.b64decode(envelope["ciphertext"], validate=True), decrypt=True)
            values = json.loads(clear.decode("utf-8"))
            _validate(values)
            return values
        except (ValueError, KeyError, TypeError, AttributeError, OSError) as exc:
            raise ValueError(
                "本机密钥文件无法读取；请使用保存时的 Windows 账号，原文件未改动。"
            ) from exc

    def _save(self, values):
        _validate(values)
        encrypted = _crypt(json.dumps(values, ensure_ascii=False).encode("utf-8"))
        payload = json.dumps(
            {
                "format": "windows-dpapi-v1",
                "ciphertext": base64.b64encode(encrypted).decode("ascii"),
            }
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, prefix=".credentials-", suffix=".tmp", delete=False
            ) as output:
                temporary = Path(output.name)
                output.write(payload.encode("utf-8"))
            os.replace(temporary, self.path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink()

    def update(self, entries: dict[str, str]):
        _validate(entries)
        existing = self.load()
        for name, value in entries.items():
            if value.strip():
                existing[name] = value.strip()
        self._save(existing)

    def delete(self, name: str):
        if name not in KEY_NAMES:
            raise ValueError("本机密钥服务商名称无效。")
        existing = self.load()
        existing.pop(name, None)
        self._save(existing)
