from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any, Callable

from src.document_source.adapters.hwpx_mapping import map_hwpx_document
from src.document_source.adapters.hwpx_package import inspect_hwpx_package
from src.document_source.model import (
    DiagnosticSeverity,
    DocumentSourceAdapterInfo,
    DocumentSourceFormat,
    DocumentSourceResult,
    SourceDiagnostic,
)
from src.document_source.signatures import probe_document_format

EXPECTED_HWPXKIT_VERSION = "0.2.1"
MAX_SOURCE_BYTES = 512 * 1024 * 1024

BackendLoader = Callable[[], Any]
VersionLoader = Callable[[], str]


def _info(version: str = EXPECTED_HWPXKIT_VERSION) -> DocumentSourceAdapterInfo:
    return DocumentSourceAdapterInfo(
        backend_name="hwpxkit",
        backend_version=version,
        supported_formats=(DocumentSourceFormat.HWPX,),
        capabilities=("sections", "paragraphs", "runs", "tables", "images", "diagnostics"),
        limitations=("no-exam-domain", "no-db", "no-gui", "no-export", "not-user-facing"),
    )


def _fail(code: str, message: str, sha: str, elapsed: float, version: str = EXPECTED_HWPXKIT_VERSION) -> DocumentSourceResult:
    diag = SourceDiagnostic(code=code, severity=DiagnosticSeverity.ERROR, message=message, backend="hwpxkit")
    return DocumentSourceResult(
        document=None,
        diagnostics=(diag,),
        adapter_info=_info(version),
        elapsed_seconds=elapsed,
        source_sha256=sha,
        success=False,
    )


def _hash_file(path: Path) -> tuple[int, str, float]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest(), path.stat().st_mtime


class HwpxSourceAdapter:
    def __init__(
        self,
        backend_loader: BackendLoader | None = None,
        version_loader: VersionLoader | None = None,
        package_inspector=inspect_hwpx_package,
    ) -> None:
        self._backend_loader = backend_loader
        self._version_loader = version_loader
        self._package_inspector = package_inspector
        self._backend = None
        self._closed = False

    def probe(self, path: str):
        return probe_document_format(path)

    def close(self) -> None:
        self._backend = None
        self._closed = True

    def _load_backend(self):
        if self._backend_loader is not None:
            backend = self._backend_loader()
            version = self._version_loader() if self._version_loader else EXPECTED_HWPXKIT_VERSION
            return backend, version
        import importlib
        import importlib.metadata

        module = importlib.import_module("hwpxkit")
        version = importlib.metadata.version("hwpxkit")
        return module, version

    def parse(self, path: str, options=None) -> DocumentSourceResult:
        started = time.perf_counter()
        source = Path(path)
        size, sha, mtime = _hash_file(source)
        elapsed = lambda: time.perf_counter() - started
        if size > MAX_SOURCE_BYTES:
            return _fail("HWPX_RESOURCE_LIMIT", "source exceeds size policy", sha, elapsed())
        probe = probe_document_format(source)
        if probe.source_format is not DocumentSourceFormat.HWPX:
            return _fail("HWPX_SIGNATURE_INVALID", "not a verified HWPX package", sha, elapsed())
        try:
            backend, version = self._load_backend()
        except ImportError:
            return _fail("HWPX_BACKEND_UNAVAILABLE", "hwpxkit is not installed", sha, elapsed())
        except Exception as exc:
            return _fail("HWPX_BACKEND_IMPORT_FAILED", type(exc).__name__, sha, elapsed())
        if version != EXPECTED_HWPXKIT_VERSION:
            return _fail("HWPX_BACKEND_VERSION_MISMATCH", f"expected {EXPECTED_HWPXKIT_VERSION}", sha, elapsed(), version)
        try:
            parsed = backend.parse_file(str(source))
        except Exception:
            return _fail("HWPX_PARSE_FAILED", "backend parse failed", sha, elapsed(), version)
        try:
            raw = parsed.to_json()
            payload = json.loads(raw)
        except Exception:
            return _fail("HWPX_JSON_INVALID", "backend JSON invalid", sha, elapsed(), version)
        if not isinstance(payload, dict):
            return _fail("HWPX_SCHEMA_UNSUPPORTED", "JSON root is not an object", sha, elapsed(), version)
        try:
            package = self._package_inspector(source)
        except Exception:
            return _fail("HWPX_PACKAGE_SUPPLEMENT_FAILED", "package supplement failed", sha, elapsed(), version)
        report = {}
        warnings = list(getattr(parsed, "warnings", None) or [])
        if hasattr(parsed, "diagnostic_report"):
            try:
                report = parsed.diagnostic_report() or {}
            except Exception:
                report = {}
        try:
            document = map_hwpx_document(
                payload=payload,
                source_identifier=source.name,
                source_bytes=size,
                source_sha256=sha,
                backend_version=version,
                package=package,
                backend_diagnostics=list(report.get("items") or []),
                backend_warnings=warnings,
            )
        except ValueError:
            return _fail("HWPX_SCHEMA_UNSUPPORTED", "unable to map backend JSON", sha, elapsed(), version)
        post_size, post_sha, post_mtime = _hash_file(source)
        if (post_size, post_sha, post_mtime) != (size, sha, mtime):
            return _fail("HWPX_PARSE_FAILED", "source mutated", sha, elapsed(), version)
        diags = document.diagnostics
        return DocumentSourceResult(
            document=document,
            diagnostics=diags,
            adapter_info=document.backend_info,
            elapsed_seconds=elapsed(),
            source_sha256=sha,
            success=True,
        )
