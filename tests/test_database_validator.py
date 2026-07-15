import sqlite3

from src.database.validator import QuestionValidator


def test_question_validator_flags_invalid_choices_answer_image_and_tags(
    repo,
    sample_metadata,
    sample_question,
    tmp_path,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    with sqlite3.connect(repo.db_path) as conn:
        conn.execute("""
            UPDATE questions
            SET question_text = '',
                session = 0,
                question_number = 0,
                correct_answer = 5,
                has_image = 1,
                image_path = ?,
                tags = '#기관1'
            WHERE id = ?
        """, (str(tmp_path / "missing.png"), question['id']))
        conn.execute(
            "DELETE FROM question_choices WHERE question_id = ? AND choice_number = 4",
            (question['id'],)
        )
        conn.execute("""
            UPDATE question_choices
            SET choice_symbol = 'X', choice_text = ''
            WHERE question_id = ? AND choice_number = 2
        """, (question['id'],))
        conn.execute("""
            UPDATE question_choices
            SET choice_image_path = ?
            WHERE question_id = ? AND choice_number = 3
        """, (str(tmp_path / "missing-choice.png"), question['id']))
        conn.commit()

    findings = QuestionValidator(repo).scan()

    assert len(findings) == 1
    finding = findings[0]
    assert finding['question_id'] == question['id']
    assert finding['severity'] == 'error'
    issue_codes = {issue['code'] for issue in finding['issues']}
    assert issue_codes == {
        'empty_question_text',
        'invalid_session',
        'invalid_question_number',
        'invalid_correct_answer',
        'choice_count',
        'empty_choice_text',
        'invalid_choice_symbol',
        'missing_image_file',
        'missing_choice_image_file',
        'missing_exam_tag',
    }
    assert '발문 없음' in finding['summary']


def test_question_validator_accepts_imported_exam_session_identifiers(
    repo,
    sample_metadata,
    sample_question,
):
    sample_question.session = 41
    sample_metadata.session = 41
    repo.save_questions([sample_question], sample_metadata)

    findings = QuestionValidator(repo).scan()

    assert all(
        issue['code'] != 'invalid_session'
        for finding in findings
        for issue in finding['issues']
    )


def test_question_validator_maps_shared_text_quality_codes(
    repo,
    sample_metadata,
    sample_question,
):
    sample_question.text = "다음 (설명에서 [0/해 값을 고르시오."
    repo.save_questions([sample_question], sample_metadata)

    codes = {
        issue["code"]
        for finding in QuestionValidator(repo).scan()
        for issue in finding["issues"]
    }

    assert {"broken_unit_text", "unbalanced_delimiter"} <= codes


def test_question_validator_accepts_clean_question(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)

    assert QuestionValidator(repo).scan() == []


def test_question_validator_accepts_descriptive_question_with_model_answer(repo):
    template = repo.get_manual_descriptive_question_template()
    template.update({
        'question_text': '해양오염 방지 절차를 설명하시오.',
        'model_answer': '오염원을 차단하고 보고 절차에 따라 신속히 조치한다.',
    })
    question_id = repo.create_manual_question(template)

    validator = QuestionValidator(repo)
    question = repo.get_question(question_id)

    assert validator.scan() == []
    assert validator.is_random_eligible(question) is False


def test_question_validator_flags_descriptive_question_missing_model_answer(repo):
    template = repo.get_manual_descriptive_question_template()
    template.update({
        'question_text': '응급조치 절차를 설명하시오.',
        'model_answer': '',
    })
    repo.create_manual_question(template)

    findings = QuestionValidator(repo).scan()

    assert len(findings) == 1
    issue_codes = {issue['code'] for issue in findings[0]['issues']}
    assert issue_codes == {'missing_model_answer'}


def test_question_validator_accepts_choice_image_without_question_image_path(
    repo,
    sample_metadata,
    sample_question,
    tmp_path,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]
    choice_image = tmp_path / "choice.png"
    choice_image.write_bytes(b"image")

    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE questions SET has_image = 1, image_path = NULL WHERE id = ?",
            (question['id'],)
        )
        conn.execute(
            """
            UPDATE question_choices
            SET choice_text = '', choice_image_path = ?
            WHERE question_id = ? AND choice_number = 1
            """,
            (str(choice_image), question['id'])
        )
        conn.commit()

    assert QuestionValidator(repo).scan() == []


def test_question_validator_accepts_legacy_choice_symbols(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    with sqlite3.connect(repo.db_path) as conn:
        conn.executemany(
            "UPDATE question_choices SET choice_symbol = ? WHERE question_id = ? AND choice_number = ?",
            [
                ("가.", question['id'], 1),
                ("나.", question['id'], 2),
                ("사.", question['id'], 3),
                ("아.", question['id'], 4),
            ],
        )
        conn.commit()

    assert QuestionValidator(repo).scan() == []


def test_question_validator_accepts_matching_numeric_choice_symbols(
    repo,
    sample_metadata,
    sample_question,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    with sqlite3.connect(repo.db_path) as conn:
        conn.executemany(
            "UPDATE question_choices SET choice_symbol = ? "
            "WHERE question_id = ? AND choice_number = ?",
            [
                (str(number), question['id'], number)
                for number in range(1, 5)
            ],
        )
        conn.commit()

    validator = QuestionValidator(repo)
    stored = repo.get_questions_with_choices(limit=1)[0]

    assert validator.scan() == []
    assert validator.is_random_eligible(stored) is True


def test_question_validator_rejects_mismatched_numeric_choice_symbol(
    repo,
    sample_metadata,
    sample_question,
):
    repo.save_questions([sample_question], sample_metadata)
    question = repo.get_questions_with_choices(limit=1)[0]

    with sqlite3.connect(repo.db_path) as conn:
        conn.execute(
            "UPDATE question_choices SET choice_symbol = '2' "
            "WHERE question_id = ? AND choice_number = 1",
            (question['id'],),
        )
        conn.commit()

    findings = QuestionValidator(repo).scan()

    assert len(findings) == 1
    assert 'invalid_choice_symbol' in {
        issue['code']
        for issue in findings[0]['issues']
    }


def test_question_validator_flags_missing_required_image(repo, sample_metadata, sample_question):
    sample_question.text = "다음 그림과 같은 회로의 명칭은?"
    sample_question.has_image = False
    sample_question.image_path = None
    repo.save_questions([sample_question], sample_metadata)

    findings = QuestionValidator(repo).scan()

    assert len(findings) == 1
    issue_codes = {issue['code'] for issue in findings[0]['issues']}
    assert 'missing_required_image' in issue_codes


def test_question_validator_flags_ocr_placeholder_and_noise(repo, sample_metadata, sample_question):
    sample_question.text = "[OCR 누락] 원본 PDF에서 문항을 확인해 주세요."
    sample_question.choices[0].text = "0卜0 으9"
    repo.save_questions([sample_question], sample_metadata)

    findings = QuestionValidator(repo).scan()

    assert len(findings) == 1
    issue_codes = {issue['code'] for issue in findings[0]['issues']}
    assert 'ocr_placeholder' in issue_codes
    assert 'ocr_noise_text' in issue_codes


def test_question_validator_does_not_flag_normal_korean_or_ohms_law(
    repo,
    sample_metadata,
    sample_question,
):
    sample_question.text = (
        "In accordance with Ohm's Law, a reduction in resistance permits an "
        "increased flow of current."
    )
    sample_question.choices[1].text = "기관실 빌지를 탱크로 모으거나 배출시킨다."
    repo.save_questions([sample_question], sample_metadata)

    assert QuestionValidator(repo).scan() == []


def test_question_validator_does_not_flag_image_choice_placeholder(
    repo,
    sample_metadata,
    sample_question,
):
    for choice in sample_question.choices:
        choice.text = "[이미지 선지]"
    repo.save_questions([sample_question], sample_metadata)

    assert QuestionValidator(repo).scan() == []


def test_question_validator_flags_suspicious_text_artifact(repo, sample_metadata, sample_question):
    sample_question.text = (
        "국제해상충돌방지규칙상 서로 시계 안에서 척의 동2 력선이 "
        "상대의 진로를 횡단할 경우 충돌의 위험이 있을 때 항법으로 옳지 않은 것은?"
    )
    repo.save_questions([sample_question], sample_metadata)

    findings = QuestionValidator(repo).scan()

    assert len(findings) == 1
    assert any(issue['code'] == 'suspicious_text_artifact' for issue in findings[0]['issues'])
    question = repo.get_questions_with_choices(limit=1)[0]
    assert not QuestionValidator(repo).is_random_eligible(question)
