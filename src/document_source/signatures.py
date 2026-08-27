from __future__ import annotations

import os
import zipfile
from pathlib import Path

from src.document_source.cfb import CFB_MAGIC, CfbError, has_hwp_fileheader
from src.document_source.model import (
    DiagnosticSeverity,
    DocumentFormatProbe,
    DocumentSourceFormat,
    ProbeConfidence,
    SourceDiagnostic,
)

PDF_WINDOW = 1024
ZIP_ENTRY_CAP = 4096
ZIP_UNCOMPRESSED_CAP = 64 * 1024 * 1024
ZIP_ENTRY_SIZE_CAP = 32 * 1024 * 1024
HWPX_MIMETYPE = "application/hwp+zip"
HWPX_REQUIRED = (
    "mimetype",
    "version.xml",
    "META-INF/manifest.xml",
    "META-INF/container.xml",
    "Contents/content.hpf",
    "Contents/header.xml",
)


def _diag(code: str, message: str, severity: DiagnosticSeverity = DiagnosticSeverity.ERROR) -> SourceDiagnostic:
    return SourceDiagnostic(code=code, severity=severity, message=message)


def probe_document_format(path: str | os.PathLike[str]) -> DocumentFormatProbe:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(str(p))
    if not p.is_file():
        return DocumentFormatProbe(
            source_format=DocumentSourceFormat.UNKNOWN,
            confidence=ProbeConfidence.UNKNOWN,
            diagnostics=(_diag("SOURCE_FILE_NOT_REGULAR", "not a regular file"),),
        )
    size = p.stat().st_size
    if size == 0:
        return DocumentFormatProbe(
            source_format=DocumentSourceFormat.UNKNOWN,
            confidence=ProbeConfidence.UNKNOWN,
            diagnostics=(_diag("SOURCE_FILE_EMPTY", "empty file"),),
        )
    with p.open("rb") as handle:
        head = handle.read(max(PDF_WINDOW, 8))
    ext = p.suffix.lower()
    diags: list[SourceDiagnostic] = []

    if b"%PDF-" in head[:PDF_WINDOW]:
        mismatch = ext not in {".pdf", ""}
        if mismatch:
            diags.append(_diag("SOURCE_EXTENSION_MISMATCH", "PDF signature with non-pdf extension", DiagnosticSeverity.WARNING))
        return DocumentFormatProbe(
            source_format=DocumentSourceFormat.PDF,
            confidence=ProbeConfidence.EXACT,
            diagnostics=tuple(diags),
            extension_mismatch=mismatch,
        )

    if head.startswith(b"PK\x03\x04") or zipfile.is_zipfile(p):
        return _probe_zip(p, ext)

    if head.startswith(CFB_MAGIC):
        return _probe_cfb(p, ext, p.read_bytes() if size <= ZIP_UNCOMPRESSED_CAP else head)

    diags.append(_diag("SOURCE_SIGNATURE_UNKNOWN", "unrecognized signature"))
    return DocumentFormatProbe(
        source_format=DocumentSourceFormat.UNKNOWN,
        confidence=ProbeConfidence.UNKNOWN,
        diagnostics=tuple(diags),
        extension_mismatch=False,
    )


def _probe_zip(path: Path, ext: str) -> DocumentFormatProbe:
    diags: list[SourceDiagnostic] = []
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            if len(names) > ZIP_ENTRY_CAP:
                diags.append(_diag("SOURCE_PROBE_RESOURCE_LIMIT", "too many zip entries"))
                return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
            if len(names) != len(set(names)):
                diags.append(_diag("SOURCE_HWPX_CONTAINER_MALFORMED", "duplicate zip entries"))
                return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
            total_unc = 0
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/"):
                    diags.append(_diag("SOURCE_HWPX_CONTAINER_MALFORMED", "unsafe zip path"))
                    return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
                if info.file_size > ZIP_ENTRY_SIZE_CAP:
                    diags.append(_diag("SOURCE_PROBE_RESOURCE_LIMIT", "zip entry too large"))
                    return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
                total_unc += info.file_size
                if info.flag_bits & 0x1:
                    diags.append(_diag("SOURCE_HWPX_CONTAINER_MALFORMED", "encrypted zip entry"))
                    return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
            if total_unc > ZIP_UNCOMPRESSED_CAP:
                diags.append(_diag("SOURCE_PROBE_RESOURCE_LIMIT", "zip uncompressed cap"))
                return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
            name_set = {n.replace("\\", "/") for n in names}
            try:
                mime = zf.read("mimetype").decode("utf-8", "replace").strip()
            except KeyError:
                mime = ""
            missing = [part for part in HWPX_REQUIRED if part not in name_set]
            has_section = any(n.startswith("Contents/section") and n.endswith(".xml") for n in name_set)
            if mime == HWPX_MIMETYPE and not missing and has_section:
                mismatch = ext not in {".hwpx", ""}
                if mismatch:
                    diags.append(_diag("SOURCE_EXTENSION_MISMATCH", "HWPX signature with non-hwpx extension", DiagnosticSeverity.WARNING))
                return DocumentFormatProbe(
                    DocumentSourceFormat.HWPX,
                    ProbeConfidence.CONTAINER_VERIFIED,
                    tuple(diags),
                    extension_mismatch=mismatch,
                )
            if mime != HWPX_MIMETYPE:
                diags.append(_diag("SOURCE_ZIP_NOT_HWPX", "zip is not an HWPX package"))
            elif missing:
                diags.append(_diag("SOURCE_HWPX_REQUIRED_PART_MISSING", "missing HWPX parts"))
            else:
                diags.append(_diag("SOURCE_ZIP_NOT_HWPX", "generic zip"))
    except zipfile.BadZipFile:
        diags.append(_diag("SOURCE_HWPX_CONTAINER_MALFORMED", "bad zip"))
    return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))


def _probe_cfb(path: Path, ext: str, data: bytes) -> DocumentFormatProbe:
    diags: list[SourceDiagnostic] = []
    try:
        if has_hwp_fileheader(data):
            mismatch = ext not in {".hwp", ""}
            if mismatch:
                diags.append(_diag("SOURCE_EXTENSION_MISMATCH", "HWP signature with non-hwp extension", DiagnosticSeverity.WARNING))
            return DocumentFormatProbe(
                DocumentSourceFormat.HWP,
                ProbeConfidence.CONTAINER_VERIFIED,
                tuple(diags),
                extension_mismatch=mismatch,
            )
        diags.append(_diag("SOURCE_CFB_NOT_HWP", "CFB without HWP FileHeader"))
        return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
    except CfbError as exc:
        message = str(exc)
        code = "SOURCE_PROBE_RESOURCE_LIMIT" if "cycle" in message or "limit" in message else "SOURCE_HWP_CFB_MALFORMED"
        diags.append(_diag(code, "malformed CFB"))
        return DocumentFormatProbe(DocumentSourceFormat.UNKNOWN, ProbeConfidence.UNKNOWN, tuple(diags))
