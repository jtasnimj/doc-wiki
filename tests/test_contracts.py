import pytest

from docwiki.config import Settings
from docwiki.contracts import normalize_questions
from docwiki.errors import AppError


def test_questions_preserve_order_wording_duplicates_and_ignore_answers():
    questions = normalize_questions(
        {"questions": ["  Which cloud? ", {"id": "q1", "question": "Which cloud?", "answer": "FAKE"}]},
        Settings(),
    )
    assert [q.question for q in questions] == ["  Which cloud? ", "Which cloud?"]
    assert questions[0].id != questions[1].id
    assert "FAKE" not in str(questions)
    with pytest.raises(AppError):
        normalize_questions([{"id": "x", "question": "a"}, {"id": "x", "question": "b"}], Settings())

