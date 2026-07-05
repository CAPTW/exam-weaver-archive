from click.testing import CliRunner

from src.cli.main import cli


def test_question_show_renders_normalized_choices(repo, sample_metadata, sample_question):
    repo.save_questions([sample_question], sample_metadata)

    result = CliRunner().invoke(
        cli,
        ['question', 'show', '1', '--db-path', repo.db_path],
    )

    assert result.exit_code == 0, result.output
    assert "기관1 2024년 1회 1번" in result.output
    assert "* ㉯ 20" in result.output
    assert "정답: 2번" in result.output
