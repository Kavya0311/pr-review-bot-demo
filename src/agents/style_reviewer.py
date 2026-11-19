
import json
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

load_dotenv(ROOT / ".env")

ALLOWED_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}


def load_parsed_data(pr_number):
    input_file = ARTIFACTS / f"pr_{pr_number}_parsed.json"

    if not input_file.exists():
        raise FileNotFoundError(f"Parsed PR file not found: {input_file}")

    with open(input_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        data = data.get("files", [])

    if not isinstance(data, list):
        raise ValueError("Invalid parsed PR data format.")

    return data


def get_added_lines(parsed_data):
    valid_lines = {}

    for item in parsed_data:
        filename = item.get("filename", "")

        for line in item.get("added_lines", []):
            line_number = line.get("line_number")

            if isinstance(line_number, int):
                valid_lines[(filename, line_number)] = line.get("code", "")

    return valid_lines


def get_issue_text(finding):
    return " ".join([
        str(finding.get("issue_type", "")),
        str(finding.get("title", "")),
        str(finding.get("explanation", ""))
    ]).lower()


def is_bug_or_security_finding(finding):
    issue_text = get_issue_text(finding)

    if "sql" in issue_text and any(
        word in issue_text
        for word in ["injection", "concatenation", "unsafe query", "dynamic sql"]
    ):
        return True

    division_words = ["division", "divide", "dividing", "denominator"]
    zero_words = ["zero", "0", "without zero check"]

    if (
        any(word in issue_text for word in division_words)
        and any(word in issue_text for word in zero_words)
    ):
        return True

    if "missing error handling" in issue_text:
        return True

    return False


def is_subjective_math_parameter_finding(finding, code):
    issue_text = get_issue_text(finding)

    naming_issue = (
        "parameter" in issue_text
        and any(word in issue_text for word in [
            "name", "descriptive", "naming"
        ])
    )

    if not naming_issue:
        return False

    match = re.match(
        r"\s*def\s+([A-Za-z_]\w*)\s*\(([^)]*)\)",
        code
    )

    if not match:
        return False

    function_name = match.group(1).lower()
    parameter_text = match.group(2)

    math_words = [
        "add", "subtract", "minus", "divide",
        "multiply", "sum", "product", "average",
        "calculate", "power"
    ]

    is_math_function = any(
        word in function_name for word in math_words
    )

    parameters = []

    for parameter in parameter_text.split(","):
        parameter = parameter.strip()

        if not parameter:
            continue

        parameter = parameter.split("=")[0].split(":")[0].strip()
        parameters.append(parameter)

    conventional_names = {"a", "b", "x", "y"}

    return (
        is_math_function
        and len(parameters) >= 2
        and all(
            re.fullmatch(r"[A-Za-z_]\w*", p)
            and p.lower() in conventional_names
            for p in parameters
        )
    )


def is_false_temporary_variable_finding(finding, code):
    issue_text = get_issue_text(finding)

    is_temporary_variable = (
        "temporary variable" in issue_text
        or "unnecessary variable" in issue_text
    )

    code_lower = code.lower()

    sql_keywords = ["select ", "insert ", "update ", "delete "]

    is_dynamic_sql = (
        any(keyword in code_lower for keyword in sql_keywords)
        and (
            "+" in code
            or ".format(" in code_lower
            or 'f"' in code_lower
            or "f'" in code_lower
        )
    )

    return is_temporary_variable and is_dynamic_sql


def get_standard_severity(finding):
    issue_text = get_issue_text(finding)

    temporary_variable_indicators = [
        "unnecessary temporary variable",
        "unnecessary variable",
        "temporary variable",
        "unused intermediate variable"
    ]

    if any(
        indicator in issue_text
        for indicator in temporary_variable_indicators
    ):
        return "LOW"

    return None


def review_style(parsed_data, valid_lines):
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    if not api_key:
        raise ValueError("GROQ_API_KEY is missing from .env.")

    client = Groq(api_key=api_key)

    prompt = f"""
You are an experienced software engineer reviewing a GitHub Pull Request.

Analyze changed code for meaningful style and maintainability problems.

Focus on:
1. Unnecessary temporary variables.
2. Poor naming that genuinely makes code difficult to understand.
3. Repeated or redundant code.
4. Poor readability and maintainability.
5. Unnecessary complexity.
6. Important coding convention violations.

DO NOT REPORT:
- SQL injection or other security vulnerabilities.
- Division by zero or other runtime bugs.
- Generic missing error handling.
- Minor formatting issues.
- Personal style preferences.
- Issues better handled by Bug Finder or Security Checker.
- A variable as unnecessary merely because it appears once.
- Conventional single-letter parameters such as a, b, x and y
  in simple mathematical functions such as divide_numbers.
- Subjective naming suggestions that do not materially improve clarity.

SEVERITY POLICY:
- Unnecessary temporary variable: LOW.
- Minor maintainability problem: LOW.
- Meaningful readability or complexity problem: MEDIUM.
- Do not assign HIGH or CRITICAL to ordinary style issues.

Rules:
- Focus on meaningful, evidence-based improvements.
- Do not invent missing requirements.
- Report only issues on added lines.
- Use exact filenames and line numbers.
- Suggest practical corrections.
- Avoid duplicate findings.

Return ONLY valid JSON in this format:

{{
    "overall_summary": "Short code quality review summary",
    "findings": [
        {{
            "filename": "sample.py",
            "line_number": 13,
            "issue_type": "Unnecessary Variable",
            "severity": "LOW",
            "title": "Unnecessary temporary variable",
            "explanation": "The variable is used only once and adds no meaningful value.",
            "suggested_fix": "Return the multiplication expression directly.",
            "confidence": 0.90
        }}
    ]
}}

Severity must be one of: CRITICAL, HIGH, MEDIUM, LOW.
Confidence must be between 0 and 1.

If no meaningful style issues are found, return an empty findings array.

Changed code:
{json.dumps(parsed_data, indent=2)}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a practical code quality reviewer. "
                    "Report only meaningful, evidence-based "
                    "maintainability improvements. "
                    "Do not duplicate security or runtime bug findings."
                )
            },
            {
                "role": "user",
                "content": prompt
            }
        ],
        response_format={"type": "json_object"},
        temperature=0.1
    )

    result = json.loads(response.choices[0].message.content)
    findings = result.get("findings", [])

    if not isinstance(findings, list):
        raise ValueError("Invalid style findings format.")

    validated_findings = []
    seen = set()

    for finding in findings:
        filename = finding.get("filename")
        line_number = finding.get("line_number")

        if not isinstance(line_number, int):
            continue

        if (filename, line_number) not in valid_lines:
            print(f"Skipped invalid line reference: {filename}:{line_number}")
            continue

        if is_bug_or_security_finding(finding):
            print(f"Skipped non-style finding: {filename}:{line_number}")
            continue

        source_code = valid_lines[(filename, line_number)]

        if is_subjective_math_parameter_finding(finding, source_code):
            print(
                f"Skipped subjective mathematical parameter naming finding: "
                f"{filename}:{line_number}"
            )
            continue

        if is_false_temporary_variable_finding(finding, source_code):
            print(
                f"Skipped false temporary-variable finding: "
                f"{filename}:{line_number}"
            )
            continue

        issue_type = str(
            finding.get("issue_type", "Code Quality")
        ).strip()

        key = (filename, line_number, issue_type.lower())

        if key in seen:
            continue

        seen.add(key)

        severity = str(finding.get("severity", "LOW")).upper()

        if severity not in ALLOWED_SEVERITIES:
            severity = "LOW"

        standard_severity = get_standard_severity(finding)

        if standard_severity:
            severity = standard_severity

        try:
            confidence = float(finding.get("confidence", 0.5))
            confidence = max(0.0, min(1.0, confidence))
        except (TypeError, ValueError):
            confidence = 0.5

        validated_findings.append({
            "filename": filename,
            "line_number": line_number,
            "issue_type": issue_type,
            "severity": severity,
            "title": str(
                finding.get("title", "Code quality improvement")
            ),
            "explanation": str(finding.get("explanation", "")),
            "suggested_fix": str(finding.get("suggested_fix", "")),
            "confidence": confidence
        })

    return {
        "model": model,
        "overall_summary": str(
            result.get("overall_summary", "Style review completed.")
        ),
        "total_findings": len(validated_findings),
        "findings": validated_findings
    }


def main():
    pr_number = sys.argv[1] if len(sys.argv) > 1 else "1"

    print(f"\nStyle Reviewer reviewing PR #{pr_number}...\n")

    try:
        parsed_data = load_parsed_data(pr_number)

        if not parsed_data:
            print("No changed files found.")
            return

        valid_lines = get_added_lines(parsed_data)

        print(f"Changed files: {len(parsed_data)}")
        print(f"Added lines available for review: {len(valid_lines)}")
        print("\nAnalyzing code quality with Groq AI...\n")

        report = review_style(parsed_data, valid_lines)

        output_file = ARTIFACTS / f"pr_{pr_number}_style_findings.json"

        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=4)

        print("SUCCESS! Style review completed.")
        print(f"Findings detected: {report['total_findings']}")

        for finding in report["findings"]:
            print(
                f"\n[{finding['severity']}] "
                f"{finding['filename']}:{finding['line_number']}"
            )
            print(f"Issue: {finding['title']}")
            print(f"Confidence: {finding['confidence']}")

        print(f"\nResults saved at: {output_file}")

    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()




