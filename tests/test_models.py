import pytest
from pydantic import ValidationError

from locqa.models import Finding, IssueType, Severity

EXAMPLE = {
    "key": "garage_rent_button",
    "issue_type": "length_overflow",
    "severity": "high",
    "source": "Арендовать",
    "target": "Жалға алу үшін басыңыз",
    "evidence": "28 символов против 10 в исходнике, ключ похож на кнопку",
    "suggestion": "Жалға алу",
    "confidence": 0.95,
    "reviewed_by_human": True,
}


def test_organizer_example_validates():
    f = Finding.model_validate(EXAMPLE)
    assert f.issue_type == IssueType.LENGTH_OVERFLOW
    assert f.model_dump(mode="json") == EXAMPLE


def test_eleven_issue_types():
    assert len(IssueType) == 11


@pytest.mark.parametrize(
    "patch",
    [{"confidence": 1.5}, {"severity": "critical"}, {"issue_type": "typo"}, {"extra": 1}],
)
def test_invalid_findings(patch):
    with pytest.raises(ValidationError):
        Finding.model_validate({**EXAMPLE, **patch})


def test_severity_rank():
    assert Severity.HIGH.rank > Severity.MEDIUM.rank > Severity.LOW.rank
