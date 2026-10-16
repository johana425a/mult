"""Encrypt only this Harness profile with the current Windows user's DPAPI."""
from __future__ import annotations
import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys

class Blob(ctypes.Structure):
    _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

def crypt(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Harness credentials require Windows DPAPI")
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_pointer = ctypes.POINTER(Blob)
    crypt32.CryptProtectData.argtypes = [blob_pointer, ctypes.c_wchar_p, blob_pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_pointer]
    crypt32.CryptProtectData.restype = wintypes.BOOL
    crypt32.CryptUnprotectData.argtypes = [blob_pointer, ctypes.POINTER(ctypes.c_wchar_p), blob_pointer, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, blob_pointer]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    raw = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(raw, ctypes.POINTER(ctypes.c_byte)))
    result = Blob()
    if decrypt:
        ok = crypt32.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(result))
    else:
        ok = crypt32.CryptProtectData(ctypes.byref(source), "DeepSteam Harness", None, None, None, 1, ctypes.byref(result))
    if not ok:
        raise RuntimeError("Windows credential encryption failed")
    try:
        return ctypes.string_at(result.data, result.size)
    finally:
        kernel32.LocalFree(result.data)

def main() -> None:
    value = json.load(sys.stdin)
    path = Path(value["path"])
    if not path.is_absolute() or path.name != "credentials.dpapi":
        raise ValueError("Invalid Harness credential path")
    if value["action"] == "read":
        result = json.loads(crypt(base64.b64decode(path.read_bytes()), True)) if path.exists() else {}
        print(json.dumps(result, ensure_ascii=False))
    elif value["action"] == "write":
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = base64.b64encode(crypt(json.dumps(value["value"], ensure_ascii=False).encode("utf-8")))
        temporary = path.with_suffix(".new")
        temporary.write_bytes(encoded)
        os.replace(temporary, path)
        print("{}")
    else:
        raise ValueError("Unknown credential operation")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        print('{"error":"credential_storage_failed"}')
        sys.exit(1)
