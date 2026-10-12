"""Windows DPAPI 凭据保护；非 Windows 或 DPAPI 失败时保留兼容回退。"""
import base64
import ctypes
import ctypes.wintypes as wt
import os


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _protect(data: bytes, unprotect: bool) -> bytes | None:
    if os.name != "nt":
        return None
    blob = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_char)))
    out = _Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if unprotect else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(blob), None, None, None, None, 0, ctypes.byref(out)):
        return None
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def encrypt(value: str) -> str | None:
    raw = _protect(value.encode("utf-8"), False)
    return base64.b64encode(raw).decode("ascii") if raw is not None else None


def decrypt(value: str) -> str | None:
    try:
        raw = base64.b64decode(value.encode("ascii"), validate=True)
        out = _protect(raw, True)
        return out.decode("utf-8") if out is not None else None
    except (ValueError, UnicodeError):
        return None
