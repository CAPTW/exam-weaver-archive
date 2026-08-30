"""Public direct-OWPML HWPX compiler for immutable `ExamDocument` input."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..choice_markers import (
    DEFAULT_CHOICE_MARKER_STYLE,
    normalize_choice_marker_style,
)
from .exam_document import ExamDocument
from .hwpx_package import HwpxBuildError, write_deterministic_package
from .hwpx_profile import DEFAULT_HWPX_PROFILE, HwpxTemplateProfile
from .hwpx_render import SemanticRenderer
from .hwpx_validation import validate_and_readback


@dataclass(frozen=True, slots=True)
class HwpxExportResult:
    output_path: Path
    output_bytes: int
    package_sha256: str
    semantic_digest: str
    warnings: tuple[str, ...]
    section_count: int
    question_count: int
    table_count: int
    image_count: int
    fallback_count: int


class HwpxCompileError(RuntimeError):
    """Compiler failure with a stable machine-readable `code`."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

    def __str__(self) -> str:
        return f"{self.code}: {super().__str__()}"


class HwpxCompiler:
    def __init__(
        self,
        *,
        choice_marker_style: str = DEFAULT_CHOICE_MARKER_STYLE,
        strict: bool = True,
        profile: HwpxTemplateProfile = DEFAULT_HWPX_PROFILE,
    ) -> None:
        self.choice_marker_style = normalize_choice_marker_style(choice_marker_style)
        self.strict = bool(strict)
        self.profile = profile

    def export_document(
        self,
        document: ExamDocument,
        output_path: str | Path,
    ) -> HwpxExportResult:
        destination = Path(output_path)
        if destination.suffix.lower() != ".hwpx" or destination.name in {"", ".hwpx"}:
            raise HwpxCompileError("HWPX_INVALID_OUTPUT_PATH", "destination must use a .hwpx filename")
        if not isinstance(document, ExamDocument):
            raise HwpxCompileError("HWPX_CONTENT_LOSS_UNRESOLVED", "input is not an ExamDocument")
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise HwpxCompileError("HWPX_INVALID_OUTPUT_PATH", "destination parent is unavailable") from exc
        if not destination.parent.is_dir() or destination.is_dir():
            raise HwpxCompileError("HWPX_INVALID_OUTPUT_PATH", "destination is not a writable file path")

        temporary: Path | None = None
        try:
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{destination.name}.",
                suffix=".tmp",
                dir=destination.parent,
            )
            os.close(descriptor)
            temporary = Path(temporary_name)
            renderer = SemanticRenderer(
                profile=self.profile,
                choice_marker_style=self.choice_marker_style,
                strict=self.strict,
            )
            rendered = renderer.render(document)
            write_deterministic_package(temporary, rendered.parts)
            validate_and_readback(temporary, rendered.manifest, rendered.image_count)
            package_bytes = temporary.read_bytes()
            package_sha256 = hashlib.sha256(package_bytes).hexdigest()
            try:
                os.replace(temporary, destination)
            except OSError as exc:
                raise HwpxBuildError("HWPX_ATOMIC_REPLACE_FAILED", "unable to atomically replace destination") from exc
            temporary = None
            return HwpxExportResult(
                output_path=destination,
                output_bytes=len(package_bytes),
                package_sha256=package_sha256,
                semantic_digest=rendered.manifest.semantic_digest,
                warnings=rendered.warnings,
                section_count=rendered.manifest.semantic_section_count,
                question_count=rendered.manifest.question_count,
                table_count=rendered.table_count,
                image_count=rendered.image_count,
                fallback_count=rendered.fallback_count,
            )
        except HwpxCompileError:
            raise
        except HwpxBuildError as exc:
            raise HwpxCompileError(exc.code, str(exc)) from exc
        except Exception as exc:
            raise HwpxCompileError("HWPX_PACKAGE_CONSTRUCTION_FAILED", "unexpected HWPX construction failure") from exc
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
