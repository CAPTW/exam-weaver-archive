from __future__ import annotations

import struct
from pathlib import Path

from src.document_source.cfb import (
    MAX_DIRECTORY_ENTRIES,
    MAX_FAT_CHAIN,
    read_named_stream,
)
from src.document_source.signatures import probe_document_format
from src.document_source.model import DocumentSourceFormat


CFB_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
HWP_SIG = b"HWP Document File"


def _dir_entry(name: str, entry_type: int, start: int, size: int, child: int = -1) -> bytes:
    encoded = name.encode("utf-16le") + b"\x00\x00"
    name_bytes = encoded.ljust(64, b"\x00")[:64]
    name_len = min(len(encoded), 64)
    return b"".join(
        [
            name_bytes,
            struct.pack("<H", name_len),
            bytes([entry_type, 0]),
            struct.pack("<iii", -1, -1, child),
            b"\x00" * 16,
            struct.pack("<I", 0),
            b"\x00" * 16,
            struct.pack("<I", start & 0xFFFFFFFF),
            struct.pack("<Q", size),
        ]
    )


def build_cfb_with_fileheader(*, in_mini: bool = False, signature: bytes = HWP_SIG) -> bytes:
    """Minimal CFB v3: sector size 512, FileHeader as regular stream (padded)."""
    sector_size = 512
    header_size = 512
    payload = signature + b"\x00" * 16
    if not in_mini:
        payload = payload.ljust(4096, b"\x00")
    data_sectors = (len(payload) + sector_size - 1) // sector_size
    # layout: FAT sector 0, DIR sector 1, data sectors 2..
    fat = [-1] * (sector_size // 4)
    fat[0] = 0xFFFFFFFD  # FATSECT
    fat[1] = 0xFFFFFFFE  # ENDOFCHAIN directory
    for i in range(data_sectors):
        fat[2 + i] = 0xFFFFFFFE if i == data_sectors - 1 else 2 + i + 1
    fat_bytes = b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in fat)

    root = _dir_entry("Root Entry", 5, 0, 0, child=1)
    header_stream = _dir_entry("FileHeader", 2, 2, len(payload))
    unused = _dir_entry("", 0, 0, 0)
    directory = (root + header_stream + unused).ljust(sector_size, b"\x00")
    data = payload.ljust(data_sectors * sector_size, b"\x00")

    header = bytearray(512)
    header[0:8] = CFB_MAGIC
    header[24:26] = struct.pack("<H", 0x003E)
    header[26:28] = struct.pack("<H", 3)
    header[28:30] = struct.pack("<H", 0xFFFE)
    header[30:32] = struct.pack("<H", 9)  # 512
    header[32:34] = struct.pack("<H", 6)  # mini 64
    header[44:48] = struct.pack("<I", 1)  # num FAT sectors
    header[48:52] = struct.pack("<I", 1)  # first dir sector
    header[56:60] = struct.pack("<I", 4096)  # mini cutoff
    header[60:64] = struct.pack("<I", 0xFFFFFFFE)
    header[64:68] = struct.pack("<I", 0)
    header[68:72] = struct.pack("<I", 0)
    header[76:80] = struct.pack("<I", 0)  # first FAT sector in DIFAT[0]
    # remaining DIFAT already zero = FREESECT

    return bytes(header) + fat_bytes + directory + data


def test_hwp_fileheader_in_regular_stream(tmp_path: Path) -> None:
    blob = build_cfb_with_fileheader(in_mini=False)
    path = tmp_path / "sample.hwp"
    path.write_bytes(blob)
    data = read_named_stream(blob, "FileHeader")
    assert data.startswith(HWP_SIG)
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.HWP


def test_generic_cfb_is_not_hwp(tmp_path: Path) -> None:
    blob = build_cfb_with_fileheader(signature=b"NOT A HWP FILE!!!!")
    path = tmp_path / "doc.xls"
    path.write_bytes(blob)
    probe = probe_document_format(path)
    assert probe.source_format is not DocumentSourceFormat.HWP
    codes = {d.code for d in probe.diagnostics}
    assert "SOURCE_CFB_NOT_HWP" in codes


def test_malformed_cfb_header(tmp_path: Path) -> None:
    path = tmp_path / "bad.hwp"
    path.write_bytes(b"\x00" * 64)
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.UNKNOWN
    codes = {d.code for d in probe.diagnostics}
    assert "SOURCE_HWP_CFB_MALFORMED" in codes or "SOURCE_SIGNATURE_UNKNOWN" in codes


def test_fat_cycle_is_bounded(tmp_path: Path) -> None:
    blob = bytearray(build_cfb_with_fileheader())
    # corrupt FAT entry 2 to point to itself
    fat_off = 512
    blob[fat_off + 8 : fat_off + 12] = struct.pack("<I", 2)
    path = tmp_path / "cycle.hwp"
    path.write_bytes(bytes(blob))
    probe = probe_document_format(path)
    assert probe.source_format is not DocumentSourceFormat.HWP or any(
        d.code == "SOURCE_PROBE_RESOURCE_LIMIT" for d in probe.diagnostics
    )


def test_cfb_caps_are_defined() -> None:
    assert MAX_FAT_CHAIN > 0
    assert MAX_DIRECTORY_ENTRIES > 0


def test_extension_mismatch_for_hwp(tmp_path: Path) -> None:
    path = tmp_path / "sample.bin"
    path.write_bytes(build_cfb_with_fileheader())
    probe = probe_document_format(path)
    assert probe.source_format is DocumentSourceFormat.HWP
    assert probe.extension_mismatch is True
