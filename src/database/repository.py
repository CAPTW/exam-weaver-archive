import sqlite3
import logging
import hashlib
import re
from datetime import date
from contextlib import nullcontext
from pathlib import Path
from typing import List, Optional, Dict, Any, Mapping, Sequence

from ..utils.tagger import build_tags
from ..parser.question import ALL_CHOICES_CORRECT
from ..parser.table_format import format_display_text

logger = logging.getLogger(__name__)

VALID_CHOICE_NUMBERS = tuple(range(1, 11))
QUESTION_TYPE_MULTIPLE_CHOICE = "multiple_choice"
QUESTION_TYPE_DESCRIPTIVE = "descriptive"
MANUAL_EXAM_CODE = "personal_questions"
MANUAL_EXAM_NAME = "개인 제작 문제"
MANUAL_SUBJECT_CODE = "manual_general"
MANUAL_SUBJECT_NAME = "개인 문제"
MANUAL_TAG = "#개인제작"
CLONED_MANUAL_TAG = "#복제수정"
DESCRIPTIVE_TAG = "#서술형"


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


class ExamRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._initialized = False

    def _get_connection(self):
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.create_function(
            "FORMAT_DISPLAY_TEXT",
            1,
            format_display_text,
            deterministic=True,
        )
        return connection

    def _ensure_initialized(self):
        if not self._initialized:
            self.init_database()

    @staticmethod
    def _normalize_choice_row(row: Dict[str, Any]) -> Dict[str, Any]:
        """Expose both DB column names and stable app-facing aliases."""
        choice_number = row.get('choice_number')
        choice_symbol = row.get('choice_symbol')
        choice_text = row.get('choice_text')
        choice_format_json = row.get('choice_format_json')
        choice_image_path = row.get('choice_image_path')

        normalized = dict(row)
        normalized['number'] = choice_number
        normalized['symbol'] = choice_symbol
        normalized['text'] = choice_text
        normalized['format_json'] = choice_format_json
        normalized['choice_image_path'] = choice_image_path
        normalized['image_path'] = choice_image_path
        return normalized

    @staticmethod
    def _dedupe_choices(choices: List[Any]) -> List[Any]:
        """Keep the first choice for each valid choice number."""
        deduped = []
        seen = set()
        for choice in choices or []:
            number = getattr(choice, 'number', None)
            if number not in VALID_CHOICE_NUMBERS or number in seen:
                continue
            seen.add(number)
            deduped.append(choice)
        return deduped

    @staticmethod
    def _choice_image_path(choice: Any) -> Optional[str]:
        if isinstance(choice, dict):
            return choice.get('choice_image_path') or choice.get('image_path')
        return getattr(choice, 'choice_image_path', None) or getattr(choice, 'image_path', None)

    @staticmethod
    def _choice_format_json(choice: Any) -> Optional[str]:
        if isinstance(choice, dict):
            return choice.get('choice_format_json') or choice.get('format_json')
        return getattr(choice, 'choice_format_json', None) or getattr(choice, 'format_json', None)

    @staticmethod
    def _choice_number(choice: Any) -> Optional[int]:
        if isinstance(choice, dict):
            return choice.get('choice_number') or choice.get('number')
        return getattr(choice, 'choice_number', None) or getattr(choice, 'number', None)

    @staticmethod
    def _choice_symbol(choice: Any) -> str:
        if isinstance(choice, dict):
            return choice.get('choice_symbol') or choice.get('symbol') or ''
        return getattr(choice, 'choice_symbol', None) or getattr(choice, 'symbol', None) or ''

    @staticmethod
    def _choice_text(choice: Any) -> str:
        if isinstance(choice, dict):
            return choice.get('choice_text') or choice.get('text') or ''
        return getattr(choice, 'choice_text', None) or getattr(choice, 'text', None) or ''

    @classmethod
    def _validate_answer_state(cls, answer_available: bool, correct_answer: Any, choices: List[Any]) -> None:
        choice_numbers = {cls._choice_number(choice) for choice in choices}
        if not answer_available:
            if correct_answer != 0:
                raise ValueError("answer_available=False requires correct_answer=0")
            return
        if correct_answer != ALL_CHOICES_CORRECT and correct_answer not in choice_numbers:
            raise ValueError("answer_available=True requires a valid choice answer")

    @classmethod
    def _merge_reparsed_choices_with_existing(
        cls,
        incoming_choices: List[Any],
        existing_choices: Dict[int, Dict[str, Any]],
    ) -> List[tuple]:
        """Preserve existing choice payloads when a reparse returns blank choices."""
        merged = []
        seen_numbers = set()

        for choice in incoming_choices:
            number = cls._choice_number(choice)
            if number not in VALID_CHOICE_NUMBERS:
                continue

            symbol = cls._choice_symbol(choice)
            text = cls._choice_text(choice)
            format_json = cls._choice_format_json(choice)
            image_path = cls._choice_image_path(choice)
            existing = existing_choices.get(number)

            if (
                existing
                and not str(text or '').strip()
                and not image_path
                and cls._existing_choice_has_payload(existing)
            ):
                merged.append((
                    number,
                    symbol or existing.get('choice_symbol') or '',
                    existing.get('choice_text') or '',
                    existing.get('choice_format_json'),
                    existing.get('choice_image_path'),
                ))
            else:
                merged.append((number, symbol, text, format_json, image_path))
            seen_numbers.add(number)

        for number in sorted(set(existing_choices) - seen_numbers):
            existing = existing_choices[number]
            if cls._existing_choice_has_payload(existing):
                merged.append((
                    number,
                    existing.get('choice_symbol') or '',
                    existing.get('choice_text') or '',
                    existing.get('choice_format_json'),
                    existing.get('choice_image_path'),
                ))

        return sorted(merged, key=lambda row: row[0])

    @staticmethod
    def _existing_choice_has_payload(choice: Dict[str, Any]) -> bool:
        return bool(
            str(choice.get('choice_text') or '').strip()
            or choice.get('choice_format_json')
            or choice.get('choice_image_path')
        )

    @staticmethod
    def _subject_code_for_name(subject_name: str) -> str:
        """Create a stable, readable code for subjects not present in seed data."""
        normalized = re.sub(r"\s+", "_", str(subject_name or "").strip().lower())
        slug = re.sub(r"[^0-9a-zA-Z가-힣_]+", "", normalized).strip("_")
        digest = hashlib.sha1(str(subject_name or "").encode('utf-8')).hexdigest()[:6]
        if not slug:
            slug = "subject"
        if len(slug) > 40:
            slug = slug[:40].rstrip("_")
        return f"auto_{slug}_{digest}"

    @staticmethod
    def _ensure_table_columns(
        cursor: sqlite3.Cursor,
        table_name: str,
        column_definitions: Dict[str, str],
    ) -> None:
        cursor.execute(f"PRAGMA table_info({table_name})")
        columns = {info[1] for info in cursor.fetchall()}
        for column_name, column_type in column_definitions.items():
            if column_name not in columns:
                cursor.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )
                logger.info("Migrated: Added '%s' column to %s table", column_name, table_name)

    @staticmethod
    def _create_index_if_possible(cursor: sqlite3.Cursor, sql: str, index_name: str) -> None:
        try:
            cursor.execute(sql)
        except sqlite3.IntegrityError as exc:
            logger.warning("Skipped index %s due to existing duplicate rows: %s", index_name, exc)
        except sqlite3.OperationalError as exc:
            logger.warning("Skipped index %s due to incompatible table shape: %s", index_name, exc)

    def _backfill_missing_tags(self, cursor: sqlite3.Cursor):
        cursor.execute("""
            SELECT
                q.id,
                q.question_text,
                q.has_image,
                s.name_ko AS subject_name,
                e.code AS exam_code
            FROM questions q
            JOIN exam_subjects es ON q.exam_subject_id = es.id
            JOIN subjects s ON es.subject_id = s.id
            JOIN exams e ON es.exam_id = e.id
            WHERE q.tags IS NULL OR TRIM(q.tags) = ''
        """)
        missing_rows = cursor.fetchall()
        if not missing_rows:
            return

        question_ids = [row[0] for row in missing_rows]
        placeholders = ",".join(["?"] * len(question_ids))
        cursor.execute(
            f"""
            SELECT question_id, choice_number, choice_symbol, choice_text
            FROM question_choices
            WHERE question_id IN ({placeholders})
            ORDER BY question_id ASC, choice_number ASC
            """,
            question_ids
        )

        choices_by_question = {question_id: [] for question_id in question_ids}
        for question_id, choice_number, choice_symbol, choice_text in cursor.fetchall():
            choices_by_question[question_id].append({
                'choice_number': choice_number,
                'choice_symbol': choice_symbol,
                'choice_text': choice_text,
            })

        updates = []
        for question_id, question_text, has_image, subject_name, exam_code in missing_rows:
            tags = build_tags(
                question_text=question_text,
                choices=choices_by_question.get(question_id, []),
                subject_name=subject_name,
                exam_type=exam_code,
                has_image=bool(has_image)
            )
            if tags:
                updates.append((tags, question_id))

        if updates:
            cursor.executemany(
                "UPDATE questions SET tags = ? WHERE id = ?",
                updates
            )
            logger.info("Migrated: Backfilled tags for %s questions", len(updates))

    def init_database(self):
        """Initialize database with schema and seed data"""
        schema_path = Path(__file__).parent / 'schema.sql'
        seed_path = Path(__file__).parent / 'seed.sql'
        
        with self._get_connection() as conn:
            with open(schema_path, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())

            cursor = conn.cursor()

            # Migration: Check tags column
            cursor.execute("PRAGMA table_info(questions)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'tags' not in columns:
                cursor.execute("ALTER TABLE questions ADD COLUMN tags TEXT")
                logger.info("Migrated: Added 'tags' column to questions table")
            if 'question_format_json' not in columns:
                cursor.execute("ALTER TABLE questions ADD COLUMN question_format_json TEXT")
                logger.info("Migrated: Added 'question_format_json' column to questions table")
            if 'explanation' not in columns:
                cursor.execute("ALTER TABLE questions ADD COLUMN explanation TEXT")
                logger.info("Migrated: Added 'explanation' column to questions table")
            if 'answer_available' not in columns:
                cursor.execute("ALTER TABLE questions ADD COLUMN answer_available BOOLEAN NOT NULL DEFAULT 1")
                cursor.execute("UPDATE questions SET answer_available = 0 WHERE correct_answer = 0")
                logger.info("Migrated: Added 'answer_available' column to questions table")
            if 'question_type' not in columns:
                cursor.execute(
                    "ALTER TABLE questions ADD COLUMN question_type TEXT NOT NULL DEFAULT 'multiple_choice'"
                )
                logger.info("Migrated: Added 'question_type' column to questions table")
            if 'model_answer' not in columns:
                cursor.execute("ALTER TABLE questions ADD COLUMN model_answer TEXT")
                logger.info("Migrated: Added 'model_answer' column to questions table")
            question_column_migrations = {
                'group_id': 'INTEGER',
                'group_order': 'INTEGER',
                'source_id': 'INTEGER',
                'source_question_id': 'TEXT',
            }
            for column_name, column_type in question_column_migrations.items():
                if column_name not in columns:
                    cursor.execute(f"ALTER TABLE questions ADD COLUMN {column_name} {column_type}")
                    logger.info("Migrated: Added '%s' column to questions table", column_name)

            cursor.execute("PRAGMA table_info(question_choices)")
            choice_columns = [info[1] for info in cursor.fetchall()]
            if 'choice_format_json' not in choice_columns:
                cursor.execute("ALTER TABLE question_choices ADD COLUMN choice_format_json TEXT")
                logger.info("Migrated: Added 'choice_format_json' column to question_choices table")
            if 'choice_image_path' not in choice_columns:
                cursor.execute("ALTER TABLE question_choices ADD COLUMN choice_image_path TEXT")
                logger.info("Migrated: Added 'choice_image_path' column to question_choices table")

            self._ensure_table_columns(cursor, 'question_sources', {
                'provider': 'TEXT',
                'source_url': 'TEXT',
                'document_id': 'TEXT',
                'attachment_url': 'TEXT',
                'attachment_filename': 'TEXT',
                'content_hash': 'TEXT',
                'fetched_at': 'DATETIME',
            })
            self._ensure_table_columns(cursor, 'question_groups', {
                'exam_subject_id': 'INTEGER',
                'year': 'INTEGER',
                'session': 'INTEGER',
                'group_number': 'INTEGER',
                'group_type': 'TEXT',
                'shared_text': 'TEXT',
                'shared_image_path': 'TEXT',
                'source_id': 'INTEGER',
                'source_page': 'INTEGER',
                'tags': 'TEXT',
                'created_at': 'DATETIME',
            })

            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_group ON questions(group_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_questions_source ON questions(source_id)")
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_question_groups_exam ON question_groups(exam_subject_id, year, session)"
            )
            self._create_index_if_possible(
                cursor,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_question_sources_unique
                ON question_sources(provider, source_url, content_hash)
                """,
                "idx_question_sources_unique",
            )
            self._create_index_if_possible(
                cursor,
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_question_groups_unique
                ON question_groups(exam_subject_id, year, session, group_number)
                """,
                "idx_question_groups_unique",
            )

            with open(seed_path, 'r', encoding='utf-8') as f:
                conn.executescript(f.read())

            self._backfill_missing_tags(cursor)
            conn.commit()
            self._initialized = True

    def save_questions(
        self,
        questions: List[Any],
        metadata: Any,
        conn: sqlite3.Connection | None = None,
    ) -> int:
        """Save parsed questions to database"""
        self._ensure_initialized()
        saved_count = 0
        connection_context = nullcontext(conn) if conn is not None else self._get_connection()
        with connection_context as active_conn:
            cursor = active_conn.cursor()
            exam_id_cache = {}
            subject_id_cache = {}
            exam_subject_id_cache = {}
            next_display_order_cache = {}

            def get_exam_id(exam_type: str) -> int:
                if exam_type not in exam_id_cache:
                    cursor.execute("SELECT id FROM exams WHERE code = ?", (exam_type,))
                    row = cursor.fetchone()
                    if not row:
                        cursor.execute(
                            """
                            INSERT INTO exams (code, name, is_domestic_only)
                            VALUES (?, ?, ?)
                            """,
                            (exam_type, exam_type, 1 if '국내' in exam_type else 0)
                        )
                        exam_id_cache[exam_type] = cursor.lastrowid
                    else:
                        exam_id_cache[exam_type] = row[0]
                return exam_id_cache[exam_type]

            def get_subject_id(subject_name: Optional[str]) -> int:
                normalized_name = subject_name or '미분류'
                if normalized_name not in subject_id_cache:
                    cursor.execute(
                        "SELECT id FROM subjects WHERE name_ko = ? OR code = ?",
                        (normalized_name, normalized_name)
                    )
                    row = cursor.fetchone()
                    if not row:
                        subject_code = self._subject_code_for_name(normalized_name)
                        cursor.execute(
                            """
                            INSERT OR IGNORE INTO subjects (code, name_ko, name_en)
                            VALUES (?, ?, ?)
                            """,
                            (subject_code, normalized_name, normalized_name)
                        )
                        cursor.execute(
                            "SELECT id FROM subjects WHERE code = ?",
                            (subject_code,)
                        )
                        row = cursor.fetchone()
                    subject_id_cache[normalized_name] = row[0]
                return subject_id_cache[normalized_name]

            def get_next_display_order(exam_id: int) -> int:
                if exam_id not in next_display_order_cache:
                    cursor.execute(
                        "SELECT COALESCE(MAX(display_order), 0) + 1 FROM exam_subjects WHERE exam_id = ?",
                        (exam_id,)
                    )
                    next_display_order_cache[exam_id] = cursor.fetchone()[0]
                display_order = next_display_order_cache[exam_id]
                next_display_order_cache[exam_id] += 1
                return display_order

            def get_exam_subject_id(exam_id: int, subject_id: int) -> int:
                key = (exam_id, subject_id)
                if key not in exam_subject_id_cache:
                    cursor.execute(
                        """
                        SELECT id
                        FROM exam_subjects
                        WHERE exam_id = ? AND subject_id = ?
                        """,
                        (exam_id, subject_id)
                    )
                    row = cursor.fetchone()
                    if not row:
                        cursor.execute(
                            """
                            INSERT INTO exam_subjects (
                                exam_id, subject_id, display_order, questions_count
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (exam_id, subject_id, get_next_display_order(exam_id), 25)
                        )
                        exam_subject_id_cache[key] = cursor.lastrowid
                    else:
                        exam_subject_id_cache[key] = row[0]
                return exam_subject_id_cache[key]

            for q in questions:
                answer_available = bool(getattr(q, 'answer_available', True))
                self._validate_answer_state(answer_available, q.correct_answer, list(q.choices or []))
                exam_type = getattr(q, 'exam_type', None) or metadata.exam_type
                exam_id = get_exam_id(exam_type)
                subject_name = getattr(q, 'subject_name', None) or '미분류'
                subject_id = get_subject_id(subject_name)
                exam_subject_id = get_exam_subject_id(exam_id, subject_id)

                # 3. Insert Question
                try:
                    year = getattr(q, 'year', None) or metadata.year
                    session = getattr(q, 'session', None) or metadata.session
                    generated_tags = build_tags(
                        question_text=q.text,
                        choices=getattr(q, 'choices', None),
                        subject_name=subject_name,
                        exam_type=exam_type,
                        has_image=bool(getattr(q, 'has_image', False))
                    )
                    tags = ",".join(dict.fromkeys(
                        tag.strip()
                        for value in (getattr(q, 'tags', ''), generated_tags)
                        for tag in str(value or '').split(',')
                        if tag.strip()
                    ))
                    cursor.execute("""
                        INSERT INTO questions (
                            exam_subject_id, year, session, question_number, 
                            question_text, question_format_json, has_image, image_path, correct_answer,
                            answer_available, source_page, tags
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        exam_subject_id, year, session, q.number,
                        q.text, getattr(q, 'format_json', None), q.has_image, getattr(q, 'image_path', None),
                        q.correct_answer, answer_available, q.source_page, tags
                    ))
                    question_id = cursor.lastrowid
                    saved_count += 1

                    # 4. Insert Choices
                    for choice in self._dedupe_choices(q.choices):
                        cursor.execute("""
                            INSERT INTO question_choices (
                                question_id, choice_number, choice_symbol, choice_text, choice_format_json, choice_image_path
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            question_id,
                            choice.number,
                            choice.symbol,
                            choice.text,
                            self._choice_format_json(choice),
                            self._choice_image_path(choice),
                        ))
                        
                except sqlite3.IntegrityError:
                    year = getattr(q, 'year', None) or metadata.year
                    session = getattr(q, 'session', None) or metadata.session
                    cursor.execute("""
                        SELECT id
                        FROM questions
                        WHERE exam_subject_id = ?
                          AND year = ?
                          AND session = ?
                          AND question_number = ?
                    """, (exam_subject_id, year, session, q.number))
                    row = cursor.fetchone()
                    if not row:
                        raise

                    question_id = row[0]
                    cursor.execute(
                        """
                        SELECT choice_number, choice_symbol, choice_text, choice_format_json, choice_image_path
                        FROM question_choices
                        WHERE question_id = ?
                        """,
                        (question_id,)
                    )
                    existing_choices = {
                        choice_row[0]: {
                            'choice_number': choice_row[0],
                            'choice_symbol': choice_row[1],
                            'choice_text': choice_row[2],
                            'choice_format_json': choice_row[3],
                            'choice_image_path': choice_row[4],
                        }
                        for choice_row in cursor.fetchall()
                    }
                    choices_to_save = self._merge_reparsed_choices_with_existing(
                        self._dedupe_choices(q.choices),
                        existing_choices,
                    )
                    cursor.execute("""
                        UPDATE questions
                        SET question_text = ?,
                            question_format_json = ?,
                            has_image = ?,
                            image_path = ?,
                            correct_answer = ?,
                            answer_available = ?,
                            source_page = ?,
                            tags = ?
                        WHERE id = ?
                    """, (
                        q.text,
                        getattr(q, 'format_json', None),
                        bool(getattr(q, 'has_image', False)),
                        getattr(q, 'image_path', None),
                        q.correct_answer,
                        answer_available,
                        q.source_page,
                        tags,
                        question_id,
                    ))
                    cursor.execute(
                        "DELETE FROM question_choices WHERE question_id = ?",
                        (question_id,)
                    )
                    for number, symbol, text, format_json, image_path in choices_to_save:
                        cursor.execute("""
                            INSERT INTO question_choices (
                                question_id, choice_number, choice_symbol, choice_text, choice_format_json, choice_image_path
                            ) VALUES (?, ?, ?, ?, ?, ?)
                        """, (
                            question_id,
                            number,
                            symbol,
                            text,
                            format_json,
                            image_path,
                        ))

                    saved_count += 1
                    logger.info(
                        "Updated existing question: %s-%s %s %s",
                        year,
                        session,
                        subject_name,
                        q.number,
                    )
                    
        return saved_count

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
        question_numbers: Optional[List[int]] = None
    ) -> List[Dict]:
        self._ensure_initialized()
        query = """
            SELECT
                q.*,
                s.name_ko as subject_name,
                e.name as exam_name,
                qg.shared_text as group_shared_text,
                qg.shared_text as shared_passage,
                qg.shared_image_path as group_shared_image_path
            FROM questions q
            JOIN exam_subjects es ON q.exam_subject_id = es.id
            JOIN subjects s ON es.subject_id = s.id
            JOIN exams e ON es.exam_id = e.id
            LEFT JOIN question_groups qg ON q.group_id = qg.id
            WHERE 1=1
        """
        params = []
        
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

        if tag_query:
            tokens = _tag_query_tokens(tag_query)
            if tokens:
                clauses = []
                tag_expr = _normalized_hashtag_sql_expression("q.tags")
                for token in tokens:
                    clauses.append(f"{tag_expr} LIKE ? ESCAPE '\\'")
                    params.append(f"% {_escape_like(token)} %")
                query += " AND (" + " OR ".join(clauses) + ")"

        if search_text:
            tokens = [t.strip() for t in search_text.split() if t.strip()]
            for token in tokens:
                token = token.lower().strip()
                if not token:
                    continue
                like = f"%{_escape_like(token)}%"
                query += """
                    AND (
                        LOWER(q.question_text) LIKE ? ESCAPE '\\'
                        OR LOWER(COALESCE(q.model_answer, '')) LIKE ? ESCAPE '\\'
                        OR LOWER(COALESCE(q.tags, '')) LIKE ? ESCAPE '\\'
                        OR LOWER(FORMAT_DISPLAY_TEXT(q.question_format_json)) LIKE ? ESCAPE '\\'
                        OR LOWER(COALESCE(qg.shared_text, '')) LIKE ? ESCAPE '\\'
                        OR EXISTS (
                            SELECT 1
                            FROM question_choices qc
                            WHERE qc.question_id = q.id
                              AND (
                                  LOWER(COALESCE(qc.choice_text, '')) LIKE ? ESCAPE '\\'
                                  OR LOWER(FORMAT_DISPLAY_TEXT(qc.choice_format_json)) LIKE ? ESCAPE '\\'
                              )
                        )
                    )
                """
                params.extend([like] * 7)

        if question_numbers:
            qnums = sorted({int(n) for n in question_numbers})
            placeholders = ",".join(["?"] * len(qnums))
            query += f" AND q.question_number IN ({placeholders})"
            params.extend(qnums)
            
        query += " ORDER BY q.year DESC, q.session DESC, q.question_number ASC"
        if limit is not None:
            query += " LIMIT ?"
            params.append(limit)
        
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(query, params)
            return [dict(row) for row in cursor.fetchall()]

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
        question_numbers: Optional[List[int]] = None
    ) -> List[Dict]:
        """Search questions and attach choices in a single batch."""
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
            question_numbers=question_numbers
        )
        if not questions:
            return []

        ids = [q['id'] for q in questions]
        placeholders = ",".join(["?"] * len(ids))
        choices_by_qid = {qid: [] for qid in ids}
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT question_id, choice_number, choice_symbol, choice_text, choice_format_json, choice_image_path
                FROM question_choices
                WHERE question_id IN ({placeholders})
                ORDER BY question_id ASC, choice_number ASC
                """,
                ids
            )
            for row in cursor.fetchall():
                choices_by_qid[row['question_id']].append(
                    self._normalize_choice_row(dict(row))
                )
            explanation_images_by_qid = self._explanation_images_by_question(conn, ids)

        for q in questions:
            q['choices'] = choices_by_qid.get(q['id'], [])
            q['explanation_images'] = explanation_images_by_qid.get(q['id'], [])

        return questions

    @staticmethod
    def _explanation_images_by_question(
        conn: sqlite3.Connection,
        question_ids: Sequence[int],
    ) -> Dict[int, List[Dict[str, Any]]]:
        result = {question_id: [] for question_id in question_ids}
        if not question_ids:
            return result

        placeholders = ",".join("?" for _ in question_ids)
        rows = conn.execute(
            f"""
            SELECT id, question_id, image_path, display_order, alt_text
            FROM question_explanation_images
            WHERE question_id IN ({placeholders})
            ORDER BY question_id ASC, display_order ASC
            """,
            list(question_ids),
        ).fetchall()
        for row in rows:
            item = dict(row)
            result[item['question_id']].append(item)
        return result

    def get_question(self, question_id: int) -> Optional[Dict]:
        self._ensure_initialized()
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT
                    q.*,
                    s.code as subject_code,
                    s.name_ko as subject_name,
                    e.code as exam_code,
                    e.name as exam_name,
                    qg.shared_text as group_shared_text,
                    qg.shared_text as shared_passage,
                    qg.shared_image_path as group_shared_image_path
                FROM questions q
                JOIN exam_subjects es ON q.exam_subject_id = es.id
                JOIN subjects s ON es.subject_id = s.id
                JOIN exams e ON es.exam_id = e.id
                LEFT JOIN question_groups qg ON q.group_id = qg.id
                WHERE q.id = ?
            """, (question_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            question = dict(row)
            
            # Get choices
            cursor.execute("SELECT * FROM question_choices WHERE question_id = ? ORDER BY choice_number", (question_id,))
            question['choices'] = [
                self._normalize_choice_row(dict(r))
                for r in cursor.fetchall()
            ]
            question['explanation_images'] = self._explanation_images_by_question(
                conn,
                [question_id],
            )[question_id]
            
            return question

    def get_statistics(self, exam_code=None, year=None) -> Dict:
        """Get database statistics"""
        self._ensure_initialized()
        stats = {}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Total questions
            where_clause = "WHERE 1=1"
            params = []
            if exam_code:
                where_clause += " AND exam_subject_id IN (SELECT id FROM exam_subjects WHERE exam_id IN (SELECT id FROM exams WHERE code = ?))"
                params.append(exam_code)
            if year:
                where_clause += " AND year = ?"
                params.append(year)
                
            cursor.execute(f"SELECT count(*) FROM questions {where_clause}", params)
            stats['total_questions'] = cursor.fetchone()[0]
            
            # Count by year
            cursor.execute(f"SELECT year, count(*) FROM questions {where_clause} GROUP BY year ORDER BY year DESC", params)
            stats['by_year'] = dict(cursor.fetchall())
            
            # Basic counts
            cursor.execute("SELECT count(*) FROM exams")
            stats['exam_count'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT count(*) FROM subjects")
            stats['subject_count'] = cursor.fetchone()[0]
            
        return stats

    def get_filter_options(self) -> Dict:
        """Get distinct filter options"""
        self._ensure_initialized()
        options = {'exams': [], 'years': [], 'sessions': []}
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT e.code, e.name
                FROM exams e
                WHERE EXISTS (
                    SELECT 1
                    FROM exam_subjects es
                    JOIN questions q ON q.exam_subject_id = es.id
                    WHERE es.exam_id = e.id
                )
                ORDER BY e.name ASC, e.code ASC
            """)
            options['exams'] = [{'code': r[0], 'name': r[1]} for r in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT year FROM questions ORDER BY year DESC")
            options['years'] = [r[0] for r in cursor.fetchall()]
            
            cursor.execute("SELECT DISTINCT session FROM questions ORDER BY session ASC")
            options['sessions'] = [r[0] for r in cursor.fetchall()]
            
        return options

    def get_subject_options(self, exam_code: Optional[str] = None) -> List[Dict]:
        """Get subject options, optionally filtered by exam code."""
        self._ensure_initialized()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if exam_code:
                cursor.execute("""
                    SELECT s.code, s.name_ko, es.display_order
                    FROM subjects s
                    JOIN exam_subjects es ON es.subject_id = s.id
                    JOIN exams e ON es.exam_id = e.id
                    JOIN questions q ON q.exam_subject_id = es.id
                    WHERE e.code = ?
                    GROUP BY s.code, s.name_ko, es.display_order
                    ORDER BY es.display_order ASC
                """, (exam_code,))
                rows = cursor.fetchall()
                return [{'code': r[0], 'name_ko': r[1]} for r in rows]

            cursor.execute("""
                SELECT DISTINCT s.code, s.name_ko
                FROM subjects s
                JOIN exam_subjects es ON es.subject_id = s.id
                JOIN questions q ON q.exam_subject_id = es.id
                ORDER BY s.name_ko ASC
            """)
            return [{'code': r[0], 'name_ko': r[1]} for r in cursor.fetchall()]

    def first_exam_code_with_questions(self) -> Optional[str]:
        """Return the first configured exam that owns at least one question."""
        self._ensure_initialized()
        with self._get_connection() as conn:
            row = conn.execute(
                """
                SELECT e.code
                FROM exams e
                JOIN exam_subjects es ON es.exam_id = e.id
                JOIN questions q ON q.exam_subject_id = es.id
                GROUP BY e.id, e.code
                ORDER BY e.id ASC
                LIMIT 1
                """
            ).fetchone()
        return row[0] if row else None

    def create_practice_attempt(
        self,
        *,
        exam_code: str,
        exam_name: str,
        questions: Sequence[Mapping[str, Any]],
    ) -> int:
        """Create a legacy mock-exam record for a local practice attempt."""
        self._ensure_initialized()
        mock_name = f"{date.today():%Y.%m.%d} {exam_name} 풀이"
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM exams WHERE code = ?",
                (exam_code,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown exam code: {exam_code}")
            cursor = conn.execute(
                "INSERT INTO mock_exams (exam_id, name) VALUES (?, ?)",
                (row[0], mock_name),
            )
            mock_exam_id = int(cursor.lastrowid)
            conn.executemany(
                """
                INSERT INTO mock_exam_questions (
                    mock_exam_id,
                    question_id,
                    display_order
                )
                VALUES (?, ?, ?)
                """,
                [
                    (mock_exam_id, int(question["id"]), display_order)
                    for display_order, question in enumerate(questions, 1)
                ],
            )
        return mock_exam_id

    def complete_practice_attempt(
        self,
        attempt_id: int,
        *,
        result: Mapping[str, Any],
        duration_seconds: int,
    ) -> None:
        """Persist overall and per-subject results for a local attempt."""
        self._ensure_initialized()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO exam_results (
                    mock_exam_id,
                    total_questions,
                    correct_count,
                    score,
                    time_spent_seconds
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    int(result.get("total") or 0),
                    int(result.get("correct") or 0),
                    float(result.get("score") or 0.0),
                    int(duration_seconds),
                ),
            )
            for exam_subject_id, stats in (result.get("subject_stats") or {}).items():
                total = int(stats.get("total") or 0)
                correct = int(stats.get("correct") or 0)
                subject_score = round((correct / total) * 100, 1) if total else 0.0
                conn.execute(
                    """
                    INSERT INTO exam_results (
                        mock_exam_id,
                        exam_subject_id,
                        total_questions,
                        correct_count,
                        score,
                        time_spent_seconds
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        attempt_id,
                        exam_subject_id,
                        total,
                        correct,
                        subject_score,
                        int(duration_seconds),
                    ),
                )

    def get_manual_question_template(self) -> Dict[str, Any]:
        """Return default values for a user-authored, non-imported question."""
        self._ensure_initialized()
        year = date.today().year
        session = 1
        return {
            'year': year,
            'session': session,
            'question_number': self.next_manual_question_number(year, session),
            'exam_code': MANUAL_EXAM_CODE,
            'exam_name': MANUAL_EXAM_NAME,
            'subject_code': MANUAL_SUBJECT_CODE,
            'subject_name': MANUAL_SUBJECT_NAME,
            'question_text': '',
            'question_type': QUESTION_TYPE_MULTIPLE_CHOICE,
            'model_answer': '',
            'correct_answer': 1,
            'answer_available': True,
            'tags': MANUAL_TAG,
            'choices': [],
        }

    def get_manual_descriptive_question_template(self) -> Dict[str, Any]:
        """Return default values for a user-authored descriptive question."""
        template = self.get_manual_question_template()
        template.update({
            'editor_title': '서술형 문제 추가',
            'question_type': QUESTION_TYPE_DESCRIPTIVE,
            'model_answer': '',
            'correct_answer': 0,
            'answer_available': False,
            'tags': self._manual_tags(f"{template.get('tags') or ''} {DESCRIPTIVE_TAG}", QUESTION_TYPE_DESCRIPTIVE),
            'choices': [],
        })
        return template

    def get_manual_question_clone_template(self, question_id: int) -> Optional[Dict[str, Any]]:
        """Return editable manual-question defaults copied from an existing question."""
        source = self.get_question(question_id)
        if not source:
            return None

        template = self.get_manual_question_template()
        shared_passage = source.get('shared_passage') or source.get('group_shared_text')
        question_text = source.get('question_text') or ''
        question_format_json = source.get('question_format_json')
        if shared_passage:
            question_text = f"[공통지문]\n{shared_passage}\n\n{question_text}"
            question_format_json = None

        question_type = self._normalize_question_type(source)
        answer_available = bool(source.get('answer_available', True))
        choices = []
        for choice in source.get('choices') or []:
            try:
                choice_number = int(choice.get('choice_number') or choice.get('number'))
            except (TypeError, ValueError):
                continue
            if choice_number not in VALID_CHOICE_NUMBERS:
                continue
            choices.append({
                'choice_number': choice_number,
                'choice_symbol': choice.get('choice_symbol') or choice.get('symbol') or str(choice_number),
                'choice_text': choice.get('choice_text') or choice.get('text') or '',
                'choice_format_json': self._choice_format_json(choice),
                'choice_image_path': self._choice_image_path(choice),
            })

        template.update({
            'editor_title': '기존 문제 복제',
            'question_text': question_text,
            'question_format_json': question_format_json,
            'question_type': question_type,
            'model_answer': source.get('model_answer') or '',
            'correct_answer': (
                0
                if question_type == QUESTION_TYPE_DESCRIPTIVE or not answer_available
                else (source.get('correct_answer') or 1)
            ),
            'answer_available': (
                False if question_type == QUESTION_TYPE_DESCRIPTIVE else answer_available
            ),
            'tags': self._manual_tags(
                f"{source.get('tags') or ''} {CLONED_MANUAL_TAG}",
                question_type,
            ),
            'explanation': source.get('explanation'),
            'image_path': source.get('image_path'),
            'choices': [] if question_type == QUESTION_TYPE_DESCRIPTIVE else choices,
        })
        return template

    def get_manual_subject_options(self) -> List[Dict[str, str]]:
        return [{'code': MANUAL_SUBJECT_CODE, 'name_ko': MANUAL_SUBJECT_NAME}]

    def next_manual_question_number(self, year: int, session: int) -> int:
        self._ensure_initialized()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COALESCE(MAX(q.question_number), 0) + 1
                FROM questions q
                JOIN exam_subjects es ON q.exam_subject_id = es.id
                JOIN exams e ON es.exam_id = e.id
                JOIN subjects s ON es.subject_id = s.id
                WHERE e.code = ?
                  AND s.code = ?
                  AND q.year = ?
                  AND q.session = ?
            """, (MANUAL_EXAM_CODE, MANUAL_SUBJECT_CODE, int(year), int(session)))
            return int(cursor.fetchone()[0] or 1)

    def create_manual_question(self, data: Dict[str, Any]) -> Optional[int]:
        """Insert a user-authored question under the manual question bucket."""
        self._ensure_initialized()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                exam_subject_id = self._ensure_exam_subject(
                    cursor,
                    exam_code=data.get('exam_code') or MANUAL_EXAM_CODE,
                    exam_name=data.get('exam_name') or MANUAL_EXAM_NAME,
                    subject_code=data.get('subject_code') or MANUAL_SUBJECT_CODE,
                    subject_name=data.get('subject_name') or MANUAL_SUBJECT_NAME,
                )
                question_type = self._normalize_question_type(data)
                is_descriptive = question_type == QUESTION_TYPE_DESCRIPTIVE
                tags = self._manual_tags(data.get('tags'), question_type)
                image_path = data.get('image_path')
                correct_answer = (
                    0 if is_descriptive else int(data.get('correct_answer') or 0)
                )
                answer_available = (
                    False
                    if is_descriptive
                    else bool(data.get('answer_available', correct_answer != 0))
                )
                if not is_descriptive:
                    self._validate_answer_state(
                        answer_available,
                        correct_answer,
                        list(data.get('choices') or []),
                    )
                cursor.execute("""
                    INSERT INTO questions (
                        exam_subject_id, year, session, question_number,
                        question_text, question_format_json, explanation,
                        question_type, model_answer,
                        has_image, image_path, correct_answer, answer_available, tags
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    exam_subject_id,
                    int(data.get('year') or date.today().year),
                    int(data.get('session') or 1),
                    int(data.get('question_number') or 1),
                    str(data.get('question_text') or '').strip(),
                    data.get('question_format_json'),
                    data.get('explanation'),
                    question_type,
                    str(data.get('model_answer') or '').strip() or None,
                    1 if image_path else 0,
                    image_path,
                    correct_answer,
                    answer_available,
                    tags,
                ))
                question_id = cursor.lastrowid
                choice_rows = []
                if not is_descriptive:
                    for choice in data.get('choices', []):
                        try:
                            choice_number = int(choice.get('choice_number') or choice.get('number'))
                        except (TypeError, ValueError):
                            continue
                        if choice_number not in VALID_CHOICE_NUMBERS:
                            continue
                        choice_rows.append((
                            question_id,
                            choice_number,
                            choice.get('choice_symbol') or choice.get('symbol') or '',
                            choice.get('choice_text') or choice.get('text') or '',
                            self._choice_format_json(choice),
                            self._choice_image_path(choice),
                        ))
                    cursor.executemany("""
                        INSERT INTO question_choices (
                            question_id, choice_number, choice_symbol, choice_text,
                            choice_format_json, choice_image_path
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, choice_rows)
                conn.commit()
                return int(question_id)
        except Exception as e:
            logger.error("Failed to create manual question: %s", e)
            return None

    def _ensure_exam_subject(
        self,
        cursor: sqlite3.Cursor,
        exam_code: str,
        exam_name: str,
        subject_code: str,
        subject_name: str,
    ) -> int:
        cursor.execute(
            "INSERT OR IGNORE INTO exams (code, name) VALUES (?, ?)",
            (exam_code, exam_name),
        )
        cursor.execute(
            "UPDATE exams SET name = ? WHERE code = ?",
            (exam_name, exam_code),
        )
        cursor.execute(
            "INSERT OR IGNORE INTO subjects (code, name_ko) VALUES (?, ?)",
            (subject_code, subject_name),
        )
        cursor.execute(
            "UPDATE subjects SET name_ko = ? WHERE code = ?",
            (subject_name, subject_code),
        )
        cursor.execute("SELECT id FROM exams WHERE code = ?", (exam_code,))
        exam_id = cursor.fetchone()[0]
        cursor.execute("SELECT id FROM subjects WHERE code = ?", (subject_code,))
        subject_id = cursor.fetchone()[0]
        cursor.execute("""
            SELECT id
            FROM exam_subjects
            WHERE exam_id = ? AND subject_id = ?
        """, (exam_id, subject_id))
        row = cursor.fetchone()
        if row:
            return int(row[0])

        cursor.execute(
            "SELECT COALESCE(MAX(display_order), 0) + 1 FROM exam_subjects WHERE exam_id = ?",
            (exam_id,),
        )
        display_order = int(cursor.fetchone()[0] or 1)
        cursor.execute("""
            INSERT INTO exam_subjects (exam_id, subject_id, display_order, questions_count)
            VALUES (?, ?, ?, ?)
        """, (exam_id, subject_id, display_order, 25))
        return int(cursor.lastrowid)

    @staticmethod
    def _normalize_question_type(data: Any) -> str:
        if isinstance(data, dict):
            raw = data.get('question_type')
        else:
            raw = getattr(data, 'question_type', None)
        value = str(raw or QUESTION_TYPE_MULTIPLE_CHOICE).strip().lower()
        if value in {'descriptive', 'subjective', 'essay', 'written'}:
            return QUESTION_TYPE_DESCRIPTIVE
        return QUESTION_TYPE_MULTIPLE_CHOICE

    @classmethod
    def _is_descriptive(cls, data: Any) -> bool:
        return cls._normalize_question_type(data) == QUESTION_TYPE_DESCRIPTIVE

    @staticmethod
    def _manual_tags(tags: Optional[str], question_type: str = QUESTION_TYPE_MULTIPLE_CHOICE) -> str:
        raw = str(tags or '').strip()
        tokens = [token.strip() for token in re.split(r"[,\s]+", raw) if token.strip()]
        normalized = {token.lower().lstrip("#") for token in tokens}
        required_tags = [
            MANUAL_TAG,
            f"#{MANUAL_EXAM_NAME.replace(' ', '')}",
            f"#{MANUAL_SUBJECT_NAME.replace(' ', '')}",
        ]
        for required_tag in required_tags:
            if required_tag.lower().lstrip("#") not in normalized:
                tokens.append(required_tag)
                normalized.add(required_tag.lower().lstrip("#"))
        if question_type == QUESTION_TYPE_DESCRIPTIVE and DESCRIPTIVE_TAG.lower().lstrip("#") not in normalized:
            tokens.append(DESCRIPTIVE_TAG)
        return ", ".join(tokens)

    def update_question(self, question_id: int, data: Dict) -> bool:
        """Update question data"""
        self._ensure_initialized()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT
                        exam_subject_id, year, session, question_number,
                        question_format_json, explanation, question_type, model_answer,
                        correct_answer, answer_available
                    FROM questions
                    WHERE id = ?
                """, (question_id,))
                current = cursor.fetchone()
                if not current:
                    return False

                exam_subject_id = data.get('exam_subject_id')
                if not exam_subject_id and data.get('exam_code') and data.get('subject_code'):
                    cursor.execute("""
                        SELECT es.id
                        FROM exam_subjects es
                        JOIN exams e ON e.id = es.exam_id
                        JOIN subjects s ON s.id = es.subject_id
                        WHERE e.code = ? AND s.code = ?
                    """, (data['exam_code'], data['subject_code']))
                    row = cursor.fetchone()
                    if not row:
                        raise ValueError(
                            f"Unknown exam/subject combination: {data['exam_code']} / {data['subject_code']}"
                    )
                    exam_subject_id = row[0]
                if not exam_subject_id:
                    exam_subject_id = current[0]

                question_type = self._normalize_question_type({
                    'question_type': data.get('question_type', current[6])
                })
                is_descriptive = question_type == QUESTION_TYPE_DESCRIPTIVE
                has_image = 1 if data.get('image_path') else 0
                if is_descriptive:
                    answer_available = False
                    correct_answer = 0
                else:
                    answer_available = bool(data.get('answer_available', current[9]))
                    correct_answer = data.get('correct_answer', current[8])
                    if 'choices' in data:
                        answer_choices = list(data.get('choices') or [])
                    else:
                        cursor.execute(
                            "SELECT choice_number FROM question_choices WHERE question_id = ?",
                            (question_id,),
                        )
                        answer_choices = [{'choice_number': row[0]} for row in cursor.fetchall()]
                    self._validate_answer_state(
                        answer_available, correct_answer, answer_choices
                    )
                cursor.execute("""
                    UPDATE questions 
                    SET
                        exam_subject_id = ?,
                        year = ?,
                        session = ?,
                        question_number = ?,
                        question_text = ?,
                        question_format_json = ?,
                        explanation = ?,
                        question_type = ?,
                        model_answer = ?,
                        correct_answer = ?,
                        answer_available = ?,
                        tags = ?,
                        image_path = ?,
                        has_image = ?
                    WHERE id = ?
                """, (
                    exam_subject_id,
                    data.get('year', current[1]),
                    data.get('session', current[2]),
                    data.get('question_number', current[3]),
                    data['question_text'],
                    data.get('question_format_json', current[4]),
                    data.get('explanation', current[5]),
                    question_type,
                    str(data.get('model_answer', current[7]) or '').strip() or None,
                    correct_answer,
                    answer_available,
                    data.get('tags', ''),
                    data.get('image_path'),
                    has_image,
                    question_id
                ))

                if is_descriptive:
                    cursor.execute(
                        "DELETE FROM question_choices WHERE question_id = ?",
                        (question_id,)
                    )
                elif 'choices' in data:
                    cursor.execute(
                        "DELETE FROM question_choices WHERE question_id = ?",
                        (question_id,)
                    )
                    cursor.executemany("""
                        INSERT INTO question_choices (
                            question_id, choice_number, choice_symbol, choice_text, choice_format_json, choice_image_path
                        ) VALUES (?, ?, ?, ?, ?, ?)
                    """, [
                        (
                            question_id,
                            choice['choice_number'],
                            choice.get('choice_symbol'),
                            choice.get('choice_text', ''),
                            self._choice_format_json(choice),
                            self._choice_image_path(choice),
                        )
                        for choice in data.get('choices', [])
                    ])
                conn.commit()
                return True
        except Exception as e:
            logger.error(f"Failed to update question {question_id}: {e}")
            return False

    def update_question_explanation(self, question_id: int, explanation: Optional[str]) -> bool:
        """Update only the user-authored explanation for a question."""
        self._ensure_initialized()
        try:
            normalized = str(explanation or '').strip() or None
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE questions SET explanation = ? WHERE id = ?",
                    (normalized, question_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to update explanation for question {question_id}: {e}")
            return False

    def delete_question(self, question_id: int) -> bool:
        """Delete a question and dependent rows."""
        self._ensure_initialized()
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "DELETE FROM mock_exam_questions WHERE question_id = ?",
                    (question_id,)
                )
                cursor.execute(
                    "DELETE FROM question_choices WHERE question_id = ?",
                    (question_id,)
                )
                cursor.execute(
                    "DELETE FROM questions WHERE id = ?",
                    (question_id,)
                )
                conn.commit()
                return cursor.rowcount > 0
        except Exception as e:
            logger.error(f"Failed to delete question {question_id}: {e}")
            return False

    def delete_questions(self, question_ids: List[int]) -> int:
        """Delete multiple questions and dependent rows."""
        self._ensure_initialized()
        ids = [int(question_id) for question_id in question_ids]
        if not ids:
            return 0

        placeholders = ",".join(["?"] * len(ids))
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"DELETE FROM mock_exam_questions WHERE question_id IN ({placeholders})",
                    ids
                )
                cursor.execute(
                    f"DELETE FROM question_choices WHERE question_id IN ({placeholders})",
                    ids
                )
                cursor.execute(
                    f"DELETE FROM questions WHERE id IN ({placeholders})",
                    ids
                )
                deleted_count = cursor.rowcount
                conn.commit()
                return deleted_count
        except Exception as e:
            logger.error(f"Failed to delete questions {ids}: {e}")
            return 0
