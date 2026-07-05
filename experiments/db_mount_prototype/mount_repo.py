from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote


NAMESPACE_SEPARATOR = "::"


def _tag_query_tokens(tag_query: str) -> List[str]:
    raw_tokens = re.split(r"[,\s]+", str(tag_query or ""))
    tokens = []
    for token in raw_tokens:
        token = token.strip().lstrip("#").lower()
        if token:
            tokens.append(f"#{token}")
    return tokens


def _normalized_hashtag_sql_expression(column_name: str) -> str:
    return (
        "LOWER(' ' || "
        f"REPLACE(REPLACE(REPLACE(COALESCE({column_name}, ''), ',', ' '), CHAR(10), ' '), CHAR(9), ' ')"
        " || ' ')"
    )


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class MountedDatabase:
    id: str
    label: str
    path: Path
    domain: str = "unknown"
    enabled: bool = True
    read_only: bool = True

    @classmethod
    def from_manifest_row(cls, row: Dict[str, Any], manifest_dir: Path) -> "MountedDatabase":
        mount_id = str(row.get("id") or "").strip()
        if not mount_id:
            raise ValueError("mount id is required")
        if NAMESPACE_SEPARATOR in mount_id:
            raise ValueError(f"mount id cannot contain {NAMESPACE_SEPARATOR!r}: {mount_id}")

        raw_path = Path(str(row.get("path") or ""))
        path = raw_path if raw_path.is_absolute() else (manifest_dir / raw_path)
        return cls(
            id=mount_id,
            label=str(row.get("label") or mount_id),
            path=path.resolve(),
            domain=str(row.get("domain") or "unknown"),
            enabled=bool(row.get("enabled", True)),
            read_only=bool(row.get("read_only", True)),
        )

    def to_manifest_row(self, manifest_dir: Path) -> Dict[str, Any]:
        try:
            path = self.path.resolve().relative_to(manifest_dir.resolve())
            path_text = path.as_posix()
        except ValueError:
            path_text = str(self.path)
        return {
            "id": self.id,
            "label": self.label,
            "domain": self.domain,
            "path": path_text,
            "enabled": self.enabled,
            "read_only": self.read_only,
        }


def namespaced_value(mount_id: str, local_value: Any) -> Optional[str]:
    if local_value is None:
        return None
    return f"{mount_id}{NAMESPACE_SEPARATOR}{local_value}"


def split_namespaced_value(value: Any) -> Tuple[Optional[str], Any]:
    if value is None:
        return None, None
    text = str(value)
    if NAMESPACE_SEPARATOR not in text:
        return None, value
    mount_id, local_value = text.split(NAMESPACE_SEPARATOR, 1)
    return mount_id or None, local_value


def load_manifest(path: str | Path) -> List[MountedDatabase]:
    manifest_path = Path(path).resolve()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    mounts = [
        MountedDatabase.from_manifest_row(row, manifest_path.parent)
        for row in payload.get("mounts", [])
    ]
    seen = set()
    for mount in mounts:
        if mount.id in seen:
            raise ValueError(f"duplicate mount id: {mount.id}")
        seen.add(mount.id)
    return mounts


def write_manifest(
    path: str | Path,
    mounts: Iterable[MountedDatabase],
    *,
    metadata: Optional[Dict[str, Any]] = None,
) -> Path:
    manifest_path = Path(path).resolve()
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    mount_list = list(mounts)
    payload = {
        "version": 1,
        "metadata": metadata or {},
        "mounts": [
            mount.to_manifest_row(manifest_path.parent)
            for mount in mount_list
        ],
    }
    manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest_path


class MountedExamRepository:
    """Read-only aggregate repository over one or more exam-bank SQLite files.

    This is deliberately scoped as a prototype. It mirrors the read APIs used by
    export/search flows, but it does not write mock exams or imported questions.
    IDs exposed to callers are namespaced as ``mount_id::local_id``.
    """

    def __init__(self, manifest_path: str | Path):
        self.manifest_path = Path(manifest_path).resolve()
        self.mounts = [mount for mount in load_manifest(self.manifest_path) if mount.enabled]
        self._mounts_by_id = {mount.id: mount for mount in self.mounts}

    def init_database(self) -> None:
        self.validate_mounts()

    def validate_mounts(self) -> None:
        if not self.mounts:
            raise ValueError(f"no enabled mounts in manifest: {self.manifest_path}")
        for mount in self.mounts:
            if not mount.path.exists():
                raise FileNotFoundError(f"mounted database not found: {mount.id} -> {mount.path}")
            with self._connect(mount) as conn:
                conn.execute("SELECT 1 FROM sqlite_master LIMIT 1").fetchone()

    def get_filter_options(self) -> Dict[str, List[Dict[str, Any]]]:
        options: Dict[str, List[Dict[str, Any]]] = {
            "mounts": [self._mount_option(mount) for mount in self.mounts],
            "exams": [],
            "years": [],
            "sessions": [],
        }
        years = set()
        sessions = set()
        for mount in self.mounts:
            with self._connect(mount) as conn:
                for row in conn.execute("SELECT code, name FROM exams ORDER BY name, code"):
                    options["exams"].append({
                        "code": namespaced_value(mount.id, row["code"]),
                        "local_code": row["code"],
                        "name": row["name"],
                        "mount_id": mount.id,
                        "mount_label": mount.label,
                        "domain": mount.domain,
                    })
                years.update(row[0] for row in conn.execute(
                    "SELECT DISTINCT year FROM questions ORDER BY year DESC"
                ))
                sessions.update(row[0] for row in conn.execute(
                    "SELECT DISTINCT session FROM questions ORDER BY session ASC"
                ))
        options["years"] = sorted(years, reverse=True)
        options["sessions"] = sorted(sessions)
        return options

    def get_subject_options(self, exam_code: Optional[str] = None) -> List[Dict[str, Any]]:
        mount_filter, local_exam_code = split_namespaced_value(exam_code)
        subjects: List[Dict[str, Any]] = []
        for mount in self._selected_mounts(mount_filter):
            with self._connect(mount) as conn:
                if local_exam_code:
                    rows = conn.execute(
                        """
                        SELECT s.code, s.name_ko, es.display_order
                        FROM subjects s
                        JOIN exam_subjects es ON es.subject_id = s.id
                        JOIN exams e ON es.exam_id = e.id
                        WHERE e.code = ?
                        ORDER BY es.display_order ASC
                        """,
                        (local_exam_code,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT DISTINCT s.code, s.name_ko, 0 AS display_order
                        FROM subjects s
                        JOIN exam_subjects es ON es.subject_id = s.id
                        ORDER BY s.name_ko ASC
                        """
                    ).fetchall()
                for row in rows:
                    subjects.append({
                        "code": namespaced_value(mount.id, row["code"]),
                        "local_code": row["code"],
                        "name_ko": row["name_ko"],
                        "mount_id": mount.id,
                        "mount_label": mount.label,
                        "domain": mount.domain,
                    })
        return subjects

    def search_questions(
        self,
        exam_code=None,
        subject_code=None,
        year=None,
        session=None,
        tag_query: Optional[str] = None,
        search_text: Optional[str] = None,
        limit=20,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        question_numbers: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        exam_mount_id, local_exam_code = split_namespaced_value(exam_code)
        subject_mount_id, local_subject_code = split_namespaced_value(subject_code)
        selected_mount_id = self._combine_mount_filters(exam_mount_id, subject_mount_id)
        rows: List[Dict[str, Any]] = []
        local_limit = limit if limit is not None else None

        for mount in self._selected_mounts(selected_mount_id):
            rows.extend(self._search_questions_one(
                mount,
                exam_code=local_exam_code,
                subject_code=local_subject_code,
                year=year,
                session=session,
                tag_query=tag_query,
                search_text=search_text,
                limit=local_limit,
                year_from=year_from,
                year_to=year_to,
                question_numbers=question_numbers,
            ))

        rows.sort(key=self._question_sort_key)
        if limit is not None:
            rows = rows[:limit]
        return rows

    def get_questions_with_choices(
        self,
        exam_code=None,
        subject_code=None,
        year=None,
        session=None,
        tag_query: Optional[str] = None,
        search_text: Optional[str] = None,
        limit=None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        question_numbers: Optional[List[int]] = None,
    ) -> List[Dict[str, Any]]:
        questions = self.search_questions(
            exam_code=exam_code,
            subject_code=subject_code,
            year=year,
            session=session,
            tag_query=tag_query,
            search_text=search_text,
            limit=limit,
            year_from=year_from,
            year_to=year_to,
            question_numbers=question_numbers,
        )
        if not questions:
            return []

        by_mount: Dict[str, List[Dict[str, Any]]] = {}
        for question in questions:
            by_mount.setdefault(question["mount_id"], []).append(question)

        for mount_id, mount_questions in by_mount.items():
            mount = self._mounts_by_id[mount_id]
            local_ids = [question["local_id"] for question in mount_questions]
            choices_by_id = self._choices_for_mount(mount, local_ids)
            for question in mount_questions:
                question["choices"] = choices_by_id.get(question["local_id"], [])
        return questions

    def get_question(self, question_id: Any) -> Optional[Dict[str, Any]]:
        mount_id, local_id = split_namespaced_value(question_id)
        if mount_id is None:
            if len(self.mounts) != 1:
                raise ValueError("raw question id is ambiguous when multiple mounts are enabled")
            mount = self.mounts[0]
            local_id = question_id
        else:
            mount = self._mounts_by_id.get(mount_id)
            if mount is None:
                return None

        with self._connect(mount) as conn:
            row = conn.execute(
                """
                SELECT
                    q.*,
                    s.code AS subject_code,
                    s.name_ko AS subject_name,
                    e.code AS exam_code,
                    e.name AS exam_name,
                    qg.shared_text AS group_shared_text,
                    qg.shared_text AS shared_passage,
                    qg.shared_image_path AS group_shared_image_path
                FROM questions q
                JOIN exam_subjects es ON q.exam_subject_id = es.id
                JOIN subjects s ON es.subject_id = s.id
                JOIN exams e ON es.exam_id = e.id
                LEFT JOIN question_groups qg ON q.group_id = qg.id
                WHERE q.id = ?
                """,
                (local_id,),
            ).fetchone()
            if row is None:
                return None
            question = self._namespace_question(mount, dict(row))
            question["choices"] = self._choices_for_mount(mount, [int(local_id)]).get(int(local_id), [])
            return question

    def get_statistics(self, exam_code=None, year=None) -> Dict[str, Any]:
        exam_mount_id, local_exam_code = split_namespaced_value(exam_code)
        stats = {
            "total_questions": 0,
            "by_year": {},
            "exam_count": 0,
            "subject_count": 0,
            "mounts": [],
        }
        for mount in self._selected_mounts(exam_mount_id):
            mount_stats = self._statistics_for_mount(mount, local_exam_code, year)
            stats["total_questions"] += mount_stats["total_questions"]
            stats["exam_count"] += mount_stats["exam_count"]
            stats["subject_count"] += mount_stats["subject_count"]
            for row_year, count in mount_stats["by_year"].items():
                stats["by_year"][row_year] = stats["by_year"].get(row_year, 0) + count
            stats["mounts"].append({
                **self._mount_option(mount),
                "statistics": mount_stats,
            })
        stats["by_year"] = dict(sorted(stats["by_year"].items(), reverse=True))
        return stats

    def _search_questions_one(self, mount: MountedDatabase, **filters) -> List[Dict[str, Any]]:
        query = """
            SELECT
                q.*,
                s.code AS subject_code,
                s.name_ko AS subject_name,
                e.code AS exam_code,
                e.name AS exam_name,
                qg.shared_text AS group_shared_text,
                qg.shared_text AS shared_passage,
                qg.shared_image_path AS group_shared_image_path
            FROM questions q
            JOIN exam_subjects es ON q.exam_subject_id = es.id
            JOIN subjects s ON es.subject_id = s.id
            JOIN exams e ON es.exam_id = e.id
            LEFT JOIN question_groups qg ON q.group_id = qg.id
            WHERE 1 = 1
        """
        params: List[Any] = []
        exam_code = filters.get("exam_code")
        subject_code = filters.get("subject_code")
        year = filters.get("year")
        session = filters.get("session")
        year_from = filters.get("year_from")
        year_to = filters.get("year_to")
        question_numbers = filters.get("question_numbers")

        if exam_code:
            query += " AND e.code = ?"
            params.append(exam_code)
        if subject_code:
            query += " AND s.code = ?"
            params.append(subject_code)
        if year is not None:
            query += " AND q.year = ?"
            params.append(year)
        else:
            if year_from is not None:
                query += " AND q.year >= ?"
                params.append(year_from)
            if year_to is not None:
                query += " AND q.year <= ?"
                params.append(year_to)
        if session:
            query += " AND q.session = ?"
            params.append(session)

        tag_query = filters.get("tag_query")
        if tag_query:
            tokens = _tag_query_tokens(tag_query)
            if tokens:
                clauses = []
                tag_expr = _normalized_hashtag_sql_expression("q.tags")
                for token in tokens:
                    clauses.append(f"{tag_expr} LIKE ? ESCAPE '\\'")
                    params.append(f"% {_escape_like(token)} %")
                query += " AND (" + " OR ".join(clauses) + ")"

        search_text = filters.get("search_text")
        if search_text:
            tokens = [token.strip() for token in search_text.split() if token.strip()]
            for token in tokens:
                like = f"%{token.lower()}%"
                query += """
                    AND (
                        LOWER(q.question_text) LIKE ?
                        OR LOWER(q.tags) LIKE ?
                        OR EXISTS (
                            SELECT 1
                            FROM question_choices qc
                            WHERE qc.question_id = q.id
                              AND LOWER(qc.choice_text) LIKE ?
                        )
                    )
                """
                params.extend([like, like, like])

        if question_numbers:
            qnums = sorted({int(number) for number in question_numbers})
            placeholders = ",".join(["?"] * len(qnums))
            query += f" AND q.question_number IN ({placeholders})"
            params.extend(qnums)

        query += " ORDER BY q.year DESC, q.session DESC, q.question_number ASC"
        limit = filters.get("limit")
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)

        with self._connect(mount) as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._namespace_question(mount, dict(row)) for row in rows]

    def _choices_for_mount(
        self,
        mount: MountedDatabase,
        local_question_ids: List[int],
    ) -> Dict[int, List[Dict[str, Any]]]:
        if not local_question_ids:
            return {}
        placeholders = ",".join(["?"] * len(local_question_ids))
        choices_by_id: Dict[int, List[Dict[str, Any]]] = {
            int(question_id): []
            for question_id in local_question_ids
        }
        with self._connect(mount) as conn:
            rows = conn.execute(
                f"""
                SELECT id, question_id, choice_number, choice_symbol, choice_text,
                       choice_format_json, choice_image_path
                FROM question_choices
                WHERE question_id IN ({placeholders})
                ORDER BY question_id ASC, choice_number ASC
                """,
                local_question_ids,
            ).fetchall()
        for row in rows:
            choice = dict(row)
            local_question_id = int(choice["question_id"])
            choice["local_id"] = choice.get("id")
            choice["local_question_id"] = local_question_id
            choice["id"] = namespaced_value(mount.id, choice.get("id"))
            choice["question_id"] = namespaced_value(mount.id, local_question_id)
            choice["mount_id"] = mount.id
            choice["number"] = choice.get("choice_number")
            choice["symbol"] = choice.get("choice_symbol")
            choice["text"] = choice.get("choice_text")
            choice["format_json"] = choice.get("choice_format_json")
            choice["image_path"] = choice.get("choice_image_path")
            choices_by_id.setdefault(local_question_id, []).append(choice)
        return choices_by_id

    def _namespace_question(self, mount: MountedDatabase, row: Dict[str, Any]) -> Dict[str, Any]:
        local_id = row.get("id")
        row["local_id"] = local_id
        row["id"] = namespaced_value(mount.id, local_id)
        row["mount_id"] = mount.id
        row["mount_label"] = mount.label
        row["domain"] = mount.domain
        row["db_path"] = str(mount.path)
        row["mounted_exam_code"] = namespaced_value(mount.id, row.get("exam_code"))
        row["mounted_subject_code"] = namespaced_value(mount.id, row.get("subject_code"))

        local_group_id = row.get("group_id")
        row["local_group_id"] = local_group_id
        if local_group_id is not None:
            row["group_id"] = namespaced_value(mount.id, local_group_id)

        local_source_id = row.get("source_id")
        row["local_source_id"] = local_source_id
        if local_source_id is not None:
            row["source_id"] = namespaced_value(mount.id, local_source_id)
        return row

    def _statistics_for_mount(
        self,
        mount: MountedDatabase,
        exam_code: Optional[str],
        year: Optional[int],
    ) -> Dict[str, Any]:
        where_clause = "WHERE 1 = 1"
        params: List[Any] = []
        if exam_code:
            where_clause += """
                AND q.exam_subject_id IN (
                    SELECT es.id
                    FROM exam_subjects es
                    JOIN exams e ON e.id = es.exam_id
                    WHERE e.code = ?
                )
            """
            params.append(exam_code)
        if year:
            where_clause += " AND q.year = ?"
            params.append(year)

        with self._connect(mount) as conn:
            total = conn.execute(
                f"SELECT COUNT(*) FROM questions q {where_clause}",
                params,
            ).fetchone()[0]
            by_year = dict(conn.execute(
                f"""
                SELECT q.year, COUNT(*)
                FROM questions q
                {where_clause}
                GROUP BY q.year
                ORDER BY q.year DESC
                """,
                params,
            ).fetchall())
            exam_count = conn.execute("SELECT COUNT(*) FROM exams").fetchone()[0]
            subject_count = conn.execute("SELECT COUNT(*) FROM subjects").fetchone()[0]
        return {
            "total_questions": total,
            "by_year": by_year,
            "exam_count": exam_count,
            "subject_count": subject_count,
        }

    def _selected_mounts(self, mount_id: Optional[str]) -> List[MountedDatabase]:
        if mount_id is None:
            return self.mounts
        mount = self._mounts_by_id.get(mount_id)
        return [mount] if mount else []

    @staticmethod
    def _combine_mount_filters(
        exam_mount_id: Optional[str],
        subject_mount_id: Optional[str],
    ) -> Optional[str]:
        if exam_mount_id and subject_mount_id and exam_mount_id != subject_mount_id:
            return "__no_matching_mount__"
        return exam_mount_id or subject_mount_id

    @staticmethod
    def _question_sort_key(question: Dict[str, Any]) -> Tuple[int, int, int, str, int]:
        return (
            -int(question.get("year") or 0),
            -int(question.get("session") or 0),
            int(question.get("question_number") or 0),
            str(question.get("mount_id") or ""),
            int(question.get("local_id") or 0),
        )

    @staticmethod
    def _mount_option(mount: MountedDatabase) -> Dict[str, Any]:
        return {
            "id": mount.id,
            "label": mount.label,
            "domain": mount.domain,
            "path": str(mount.path),
            "read_only": mount.read_only,
        }

    @staticmethod
    def _connect(mount: MountedDatabase) -> sqlite3.Connection:
        if mount.read_only:
            path = quote(str(mount.path).replace("\\", "/"), safe="/:")
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        else:
            conn = sqlite3.connect(mount.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn
