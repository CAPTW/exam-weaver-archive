from __future__ import annotations

from typing import Protocol

from src.document_source.model import DocumentFormatProbe, DocumentSourceResult


class DocumentSourceAdapter(Protocol):
    def probe(self, path: str) -> DocumentFormatProbe:
        ...

    def parse(self, path: str, options=None) -> DocumentSourceResult:
        ...

    def close(self) -> None:
        ...
