"""Render source PDF pages for unresolved rich-text findings."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable
from urllib.parse import unquote, urlparse

import fitz

from .text_repair import TextFinding


LEGACY_MARITIME_SOURCE_FILES = {
    2018: {
        "3급기관사": Path("2018/2018_engineer_3.pdf"),
        "4급기관사": Path("2018/2018_engineer_4.pdf"),
        "3급항해사": Path("2018/2018_sailor_3.pdf"),
        "4급항해사": Path("2018/2018_sailor_4.pdf"),
    },
    2019: {
        "3급기관사": Path("2019/2019_201903.pdf"),
        "4급기관사": Path("2019/2019_201904.pdf"),
        "3급항해사": Path("2019/2019_201913.pdf"),
        "4급항해사": Path("2019/2019_201914.pdf"),
    },
}


@dataclass(frozen=True)
class SourceEvidence:
    source_url: str
    source_page: int
    status: str
    image_path: Path | None
    finding_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_url": self.source_url,
            "source_page": self.source_page,
            "status": self.status,
            "image_path": (
                str(self.image_path) if self.image_path else None
            ),
            "finding_count": self.finding_count,
        }


def attach_legacy_maritime_sources(
    findings: Iterable[TextFinding],
    source_root: Path,
) -> tuple[TextFinding, ...]:
    """Attach known 2018/2019 source PDFs to legacy records for review."""

    root = Path(source_root).resolve()
    enriched: list[TextFinding] = []
    for finding in findings:
        metadata = dict(finding.metadata)
        if metadata.get("source_url"):
            enriched.append(finding)
            continue
        try:
            year = int(metadata.get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        exam_code = str(metadata.get("exam_code") or "").strip()
        relative = next(
            (
                value
                for prefix, value in LEGACY_MARITIME_SOURCE_FILES.get(
                    year, {}
                ).items()
                if exam_code.startswith(prefix)
            ),
            None,
        )
        if relative is None:
            enriched.append(finding)
            continue
        source_path = root / relative
        metadata.update({
            "source_url": source_path.as_uri(),
            "source_document": source_path.name,
        })
        enriched.append(replace(finding, metadata=metadata))
    return tuple(enriched)


def render_source_evidence(
    findings: Iterable[TextFinding],
    output_dir: Path,
) -> tuple[SourceEvidence, ...]:
    """Render each unique source URL/page once at review resolution."""

    grouped: dict[tuple[str, int], list[TextFinding]] = {}
    for finding in findings:
        source_url = str(finding.metadata.get("source_url") or "")
        source_page = int(finding.metadata.get("source_page") or 0)
        if source_url and source_page > 0:
            grouped.setdefault((source_url, source_page), []).append(
                finding
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[SourceEvidence] = []
    for index, ((source_url, source_page), matches) in enumerate(
        sorted(grouped.items()),
        start=1,
    ):
        source_path = _file_url_path(source_url)
        if source_path is None or not source_path.is_file():
            results.append(SourceEvidence(
                source_url,
                source_page,
                "source_unavailable",
                None,
                len(matches),
            ))
            continue
        try:
            with fitz.open(source_path) as document:
                if source_page > document.page_count:
                    results.append(SourceEvidence(
                        source_url,
                        source_page,
                        "page_unavailable",
                        None,
                        len(matches),
                    ))
                    continue
                image_path = (
                    output_dir
                    / f"source_{index:04d}_page_{source_page}.png"
                )
                pixmap = document[source_page - 1].get_pixmap(
                    matrix=fitz.Matrix(2.5, 2.5),
                    alpha=False,
                )
                pixmap.save(image_path)
        except (OSError, RuntimeError, ValueError):
            results.append(SourceEvidence(
                source_url,
                source_page,
                "source_unreadable",
                None,
                len(matches),
            ))
            continue
        results.append(SourceEvidence(
            source_url,
            source_page,
            "rendered",
            image_path,
            len(matches),
        ))
    return tuple(results)


def _file_url_path(source_url: str) -> Path | None:
    parsed = urlparse(source_url)
    if parsed.scheme not in ("", "file"):
        return None
    decoded = unquote(parsed.path)
    if parsed.netloc:
        decoded = f"//{parsed.netloc}{decoded}"
    if len(decoded) >= 3 and decoded[0] == "/" and decoded[2] == ":":
        decoded = decoded[1:]
    return Path(decoded)
