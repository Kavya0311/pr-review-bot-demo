
import pytest

from src.review.review_coordinator import (
    normalize_issue,
    combine_findings,
    calculate_risk
)


def test_sql_injection_normalization():
    first = normalize_issue(
        "SQL injection via string concatenation",
        "Security"
    )

    second = normalize_issue(
        "Unsafe string concatenation in SQL query",
        "Unnecessary Complexity"
    )

    assert first == second == "sql injection"


def test_division_by_zero_normalization():
    first = normalize_issue(
        "Potential division by zero",
        "Bug"
    )

    second = normalize_issue(
        "Division without zero check",
        "Missing Error Handling"
    )

    assert first == second == "division by zero"


def test_duplicate_findings_are_merged():
    agents = {
        "Bug Finder": [
            {
                "filename": "sample.py",
                "line_number": 9,
                "issue_type": "Bug",
                "title": "Division by zero",
                "severity": "MEDIUM",
                "confidence": 0.96
            }
        ],
        "Style Reviewer": [
            {
                "filename": "sample.py",
                "line_number": 9,
                "issue_type": "Missing Error Handling",
                "title": "Division without zero check",
                "severity": "HIGH",
                "confidence": 0.93
            }
        ]
    }

    result = combine_findings(agents)

    assert len(result) == 1
    assert result[0]["severity"] == "HIGH"
    assert len(result[0]["agents"]) == 2


def test_different_issues_on_same_line_are_preserved():
    agents = {
        "Bug Finder": [
            {
                "filename": "sample.py",
                "line_number": 5,
                "issue_type": "Bug",
                "title": "Division by zero",
                "severity": "MEDIUM",
                "confidence": 0.9
            },
            {
                "filename": "sample.py",
                "line_number": 5,
                "issue_type": "Security",
                "title": "SQL injection",
                "severity": "HIGH",
                "confidence": 0.95
            }
        ]
    }

    result = combine_findings(agents)

    assert len(result) == 2


def test_risk_score_calculation():
    findings = [
        {
            "severity": "HIGH",
            "confidence": 0.99
        },
        {
            "severity": "HIGH",
            "confidence": 0.96
        },
        {
            "severity": "LOW",
            "confidence": 0.92
        }
    ]

    score, level = calculate_risk(findings)

    assert score == 52
    assert level == "HIGH"


def test_empty_findings():
    score, level = calculate_risk([])

    assert score == 0
    assert level == "NO ISSUES"
