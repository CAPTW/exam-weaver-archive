from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, Union

PropertyValue = Union[str, int, float, bool, None]


class DocumentSourceFormat(Enum):
    PDF = "PDF"
    HWP = "HWP"
    HWPX = "HWPX"
    UNKNOWN = "UNKNOWN"


class DiagnosticSeverity(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class LayoutBreakKind(Enum):
    PAGE = "PAGE"
    COLUMN = "COLUMN"
    SECTION = "SECTION"


class ProbeConfidence(Enum):
    EXACT = "EXACT"
    CONTAINER_VERIFIED = "CONTAINER_VERIFIED"
    UNKNOWN = "UNKNOWN"


def _require_tuple(value: object, name: str) -> tuple:
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        raise TypeError(f"{name} must be a tuple, not list")
    raise TypeError(f"{name} must be a tuple")


@dataclass(frozen=True, slots=True)
class SourceProperty:
    name: str
    value: PropertyValue

    def __post_init__(self) -> None:
        if not isinstance(self.value, (str, int, float, bool, type(None))):
            raise TypeError("property value must be JSON-representable")


@dataclass(frozen=True, slots=True)
class SourceCoordinate:
    part: str | None = None
    page_number: int | None = None
    block_id: str | None = None
    char_start: int | None = None
    char_end: int | None = None
    x0: float | None = None
    y0: float | None = None
    x1: float | None = None
    y1: float | None = None
    unit: str | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))
        if self.page_number is not None and self.page_number < 1:
            raise ValueError("page_number must be >= 1")
        if self.char_start is not None and self.char_start < 0:
            raise ValueError("char_start must be >= 0")
        if (
            self.char_start is not None
            and self.char_end is not None
            and self.char_end < self.char_start
        ):
            raise ValueError("char_end must be >= char_start")
        if self.x0 is not None and self.x1 is not None and self.x1 < self.x0:
            raise ValueError("x1 must be >= x0")
        if self.y0 is not None and self.y1 is not None and self.y1 < self.y0:
            raise ValueError("y1 must be >= y0")
        coords = (self.x0, self.y0, self.x1, self.y1, self.char_start, self.char_end, self.page_number)
        if any(v is not None for v in coords) and not (self.unit or "").strip():
            raise ValueError("empty unit rejected when coordinates exist")


@dataclass(frozen=True, slots=True)
class SourceDiagnostic:
    code: str
    severity: DiagnosticSeverity
    message: str
    coordinate: SourceCoordinate | None = None
    backend: str | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class SourceAttachment:
    attachment_id: str
    media_type: str
    byte_size: int
    sha256: str
    local_reference: str | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))
        if self.byte_size < 0:
            raise ValueError("byte_size")
        if len(self.sha256) != 64:
            raise ValueError("sha256")


@dataclass(frozen=True, slots=True)
class DocumentRun:
    text: str
    coordinate: SourceCoordinate | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class DocumentField:
    field_type: str
    text: str
    coordinate: SourceCoordinate | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class DocumentParagraph:
    runs: tuple[DocumentRun, ...]
    coordinate: SourceCoordinate | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "runs", _require_tuple(self.runs, "runs"))
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))

    @property
    def text(self) -> str:
        return "".join(run.text for run in self.runs)


@dataclass(frozen=True, slots=True)
class DocumentTableCell:
    row: int
    column: int
    row_span: int
    column_span: int
    paragraphs: tuple[DocumentParagraph, ...]
    coordinate: SourceCoordinate | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "paragraphs", _require_tuple(self.paragraphs, "paragraphs"))
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))
        if self.row < 0 or self.column < 0:
            raise ValueError("row/column >= 0")
        if self.row_span < 1 or self.column_span < 1:
            raise ValueError("spans >= 1")


@dataclass(frozen=True, slots=True)
class DocumentTableRow:
    row_index: int
    cells: tuple[DocumentTableCell, ...]
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _require_tuple(self.cells, "cells"))
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class DocumentTable:
    table_id: str
    row_count: int
    column_count: int
    rows: tuple[DocumentTableRow, ...]
    coordinate: SourceCoordinate | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", _require_tuple(self.rows, "rows"))
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))
        occupied: set[tuple[int, int]] = set()
        for row in self.rows:
            for cell in row.cells:
                if cell.row + cell.row_span > self.row_count or cell.column + cell.column_span > self.column_count:
                    raise ValueError("cell out of range")
                for r in range(cell.row, cell.row + cell.row_span):
                    for c in range(cell.column, cell.column + cell.column_span):
                        key = (r, c)
                        if key in occupied:
                            raise ValueError("overlapping cells")
                        occupied.add(key)


@dataclass(frozen=True, slots=True)
class DocumentImage:
    image_id: str
    attachment_id: str
    media_type: str
    width: float | None = None
    height: float | None = None
    coordinate: SourceCoordinate | None = None
    alt_text: str | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class DocumentLayoutBreak:
    kind: LayoutBreakKind
    coordinate: SourceCoordinate | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


DocumentBlock = Union[
    DocumentParagraph,
    DocumentTable,
    DocumentImage,
    DocumentLayoutBreak,
    DocumentField,
]


@dataclass(frozen=True, slots=True)
class DocumentSection:
    section_id: str
    blocks: tuple[DocumentBlock, ...]
    page_width: float | None = None
    page_height: float | None = None
    column_count: int | None = None
    column_gap: float | None = None
    coordinate: SourceCoordinate | None = None
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", _require_tuple(self.blocks, "blocks"))
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class DocumentMasterPage:
    master_page_id: str
    kind: str
    blocks: tuple[DocumentBlock, ...]
    properties: tuple[SourceProperty, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "blocks", _require_tuple(self.blocks, "blocks"))
        object.__setattr__(self, "properties", _require_tuple(self.properties, "properties"))


@dataclass(frozen=True, slots=True)
class DocumentSourceAdapterInfo:
    backend_name: str
    backend_version: str
    supported_formats: tuple[DocumentSourceFormat, ...]
    capabilities: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "supported_formats", _require_tuple(self.supported_formats, "supported_formats"))
        object.__setattr__(self, "capabilities", _require_tuple(self.capabilities, "capabilities"))
        object.__setattr__(self, "limitations", _require_tuple(self.limitations, "limitations"))


@dataclass(frozen=True, slots=True)
class DocumentFormatProbe:
    source_format: DocumentSourceFormat
    confidence: ProbeConfidence
    diagnostics: tuple[SourceDiagnostic, ...]
    extension_mismatch: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", _require_tuple(self.diagnostics, "diagnostics"))


@dataclass(frozen=True, slots=True)
class DocumentSource:
    source_format: DocumentSourceFormat
    source_identifier: str
    source_bytes: int
    source_sha256: str
    backend_info: DocumentSourceAdapterInfo
    sections: tuple[DocumentSection, ...]
    master_pages: tuple[DocumentMasterPage, ...]
    attachments: tuple[SourceAttachment, ...]
    metadata: tuple[SourceProperty, ...]
    diagnostics: tuple[SourceDiagnostic, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sections", _require_tuple(self.sections, "sections"))
        object.__setattr__(self, "master_pages", _require_tuple(self.master_pages, "master_pages"))
        object.__setattr__(self, "attachments", _require_tuple(self.attachments, "attachments"))
        object.__setattr__(self, "metadata", _require_tuple(self.metadata, "metadata"))
        object.__setattr__(self, "diagnostics", _require_tuple(self.diagnostics, "diagnostics"))
        if len(self.source_sha256) != 64:
            raise ValueError("source hash")
        section_ids = [s.section_id for s in self.sections]
        if len(section_ids) != len(set(section_ids)):
            raise ValueError("section IDs unique")
        att_ids = {a.attachment_id for a in self.attachments}
        if len(att_ids) != len(self.attachments):
            raise ValueError("attachment IDs unique")
        master_ids = [m.master_page_id for m in self.master_pages]
        if len(master_ids) != len(set(master_ids)):
            raise ValueError("master-page IDs unique")
        for section in self.sections:
            for block in section.blocks:
                if isinstance(block, DocumentImage) and block.attachment_id not in att_ids:
                    raise ValueError("image attachment must resolve")


@dataclass(frozen=True, slots=True)
class DocumentSourceResult:
    document: DocumentSource | None
    diagnostics: tuple[SourceDiagnostic, ...]
    adapter_info: DocumentSourceAdapterInfo
    elapsed_seconds: float
    source_sha256: str
    success: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "diagnostics", _require_tuple(self.diagnostics, "diagnostics"))


class DocumentSourceAdapter(Protocol):
    def probe(self, path: str):
        ...

    def parse(self, path: str, options=None) -> DocumentSourceResult:
        ...

    def close(self) -> None:
        ...
