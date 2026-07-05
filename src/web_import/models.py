"""Shared models for COMCBT web import workflows."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from types import SimpleNamespace
from typing import Optional

from src.parser.question import Question


@dataclass(frozen=True)
class ComcbtExamBoard:
    name: str
    url: str
    mid: str


@dataclass(frozen=True)
class ComcbtDocument:
    title: str
    url: str
    mid: str
    document_srl: str
    year: Optional[int] = None
    month: Optional[int] = None
    day: Optional[int] = None
    session: Optional[int] = None


@dataclass(frozen=True)
class ComcbtAttachment:
    filename: str
    url: str
    role: str
    extension: str


@dataclass
class ComcbtQuestionGroup:
    group_id: str
    text: str
    child_numbers: list[int] = field(default_factory=list)
    range_start: Optional[int] = None
    range_end: Optional[int] = None
    explicit_range: bool = False
    ambiguous_range: bool = False
    source_page: Optional[int] = None


@dataclass
class ComcbtParseResult:
    questions: list[Question]
    groups: list[ComcbtQuestionGroup] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)


@dataclass
class ComcbtParsedExam:
    title: str
    source_url: str
    exam_type: str
    subject_name: str
    year: int
    session: int
    questions: list[Question]
    attachments: list[ComcbtAttachment]
    selected_attachment: Optional[ComcbtAttachment] = None
    groups: list[ComcbtQuestionGroup] = field(default_factory=list)
    diagnostics: dict[str, object] = field(default_factory=dict)

    @property
    def metadata(self) -> SimpleNamespace:
        return SimpleNamespace(
            year=self.year,
            session=self.session,
            exam_type=self.exam_type,
        )

    def to_summary(self) -> dict:
        return {
            "title": self.title,
            "source_url": self.source_url,
            "exam_type": self.exam_type,
            "subject_name": self.subject_name,
            "year": self.year,
            "session": self.session,
            "question_count": len(self.questions),
            "answer_count": sum(1 for question in self.questions if question.correct_answer),
            "attachments": [asdict(attachment) for attachment in self.attachments],
            "selected_attachment": asdict(self.selected_attachment) if self.selected_attachment else None,
            "groups": [asdict(group) for group in self.groups],
            "diagnostics": dict(self.diagnostics),
        }
