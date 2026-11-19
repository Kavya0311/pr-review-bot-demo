
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq


# Project paths
ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

load_dotenv(ROOT / ".env")


ALLOWED_SEVERITIES = {
    "CRITICAL", "HIGH", "MEDIUM", "LOW"
}


def load_parsed_data(pr_number):
    input_file = ARTIFACTS / f"pr_{pr_number}_parsed.json"

    if not input_file.exists():
        raise FileNotFoundError(
            f"Parsed PR file not found: {input_file}\n"
            "Run the diff parser first."
        )

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
            code = line.get("code", "")

            if isinstance(line_number, int):
                valid_lines[(filename, line_number)] = code

    return valid_lines


def get_standard_severity(finding, code):
    """
    Apply consistent severity rules for known issue categories.
    Unknown issue categories retain the AI-provided severity.
    """

    issue_text = " ".join([
        str(finding.get("issue_type", "")),
        str(finding.get("title", "")),
        str(finding.get("explanation", ""))
    ]).lower()

    # SQL injection is always HIGH.
    sql_indicators = [
        "injection",
        "unsafe",
        "concatenation",
        "string construction",
        "dynamic sql"
    ]

    if (
        "sql" in issue_text
        and any(word in issue_text for word in sql_indicators)
    ):
        return "HIGH"

    # Division by zero is consistently MEDIUM.
    division_words = [
        "division",
        "divide",
        "dividing",
        "denominator"
    ]

    zero_words = [
        "zero",
        "0",
        "without zero check",
        "zero check"
    ]

    if (
        any(word in issue_text for word in division_words)
        and any(word in issue_text for word in zero_words)
    ):
        return "MEDIUM"

    # Keep the AI severity for other issue categories.
    return None


def review_code(parsed_data, valid_lines):
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    if not api_key:
        raise ValueError("GROQ_API_KEY is missing from your .env file.")

    client = Groq(api_key=api_key)

    prompt = f"""
You are an experienced software engineer performing a
bug-focused review of GitHub Pull Request changes.

Analyze the supplied changed code carefully.

Your responsibilities:
1. Identify genuine programming bugs.
2. Detect incorrect logic and runtime errors.
3. Detect possible division-by-zero errors.
4. Identify unsafe code that can cause application failures.
5. Detect SQL injection where supported by code evidence.
6. Avoid reporting correct code as a bug.
7. Do not invent problems without evidence.
8. Report only issues associated with supplied added lines.
9. Do not report formatting or naming suggestions as bugs.
10. Avoid duplicate findings for the same issue.

SEVERITY POLICY - FOLLOW EXACTLY:

- SQL injection: HIGH.
- Division by zero: MEDIUM.
- Unnecessary temporary variables: Do not report as bugs.
- Other issues: Choose severity based on actual impact.

Severity definitions:
- CRITICAL: Severe impact, such as a major security compromise.
- HIGH: Serious security vulnerability or major application failure.
- MEDIUM: Runtime errors or functional problems in specific conditions.
- LOW: Minor issues with limited impact.

IMPORTANT:
- Use the exact filename and line number supplied.
- Only report line numbers present in the added code.
- Give a clear explanation of the problem.
- Suggest a practical correction.
- Do not increase severity just to make an issue appear important.

Return ONLY valid JSON in this format:

{{
    "overall_summary": "Short summary of the bug review",
    "findings": [
        {{
            "filename": "sample.py",
            "line_number": 9,
            "issue_type": "Division by Zero",
            "severity": "MEDIUM",
            "title": "Possible division by zero",
            "explanation": "The denominator may be zero, causing a runtime error.",
            "suggested_fix": "Check whether the denominator is zero before division.",
            "confidence": 0.95
        }}
    ]
}}

Severity must be one of:
CRITICAL, HIGH, MEDIUM, LOW.

Confidence must be a number between 0 and 1.

If no genuine bugs are found, return an empty findings array.

Changed code:
{json.dumps(parsed_data, indent=2)}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a precise bug detection agent. "
                    "Follow the supplied severity policy exactly. "
                    "Report only genuine, evidence-based issues."
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
        raise ValueError("The AI returned an invalid findings format.")

    validated_findings = []
    seen = set()

    for finding in findings:
        filename = finding.get("filename")
        line_number = finding.get("line_number")

        if not isinstance(line_number, int):
            continue

        if (filename, line_number) not in valid_lines:
            print(
                f"Skipped invalid line reference: "
                f"{filename}:{line_number}"
            )
            continue

        issue_type = str(
            finding.get("issue_type", "General Bug")
        ).strip()

        key = (
            filename,
            line_number,
            issue_type.lower()
        )

        if key in seen:
            continue

        seen.add(key)

        severity = str(
            finding.get("severity", "MEDIUM")
        ).upper()

        if severity not in ALLOWED_SEVERITIES:
            severity = "MEDIUM"

        # Apply deterministic severity rules.
        standard_severity = get_standard_severity(
            finding,
            valid_lines[(filename, line_number)]
        )

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
            "title": str(finding.get("title", "Potential bug")),
            "explanation": str(
                finding.get("explanation", "")
            ),
            "suggested_fix": str(
                finding.get("suggested_fix", "")
            ),
            "confidence": confidence
        })

    return {
        "model": model,
        "overall_summary": str(
            result.get("overall_summary", "Bug review completed.")
        ),
        "total_findings": len(validated_findings),
        "findings": validated_findings
    }


def main():
    pr_number = sys.argv[1] if len(sys.argv) > 1 else "1"

    print(f"\nBug Finder Agent reviewing PR #{pr_number}...\n")

    try:
        parsed_data = load_parsed_data(pr_number)

        if not parsed_data:
            print("No changed files found.")
            return

        valid_lines = get_added_lines(parsed_data)

        print(f"Changed files: {len(parsed_data)}")
        print(f"Added lines available for review: {len(valid_lines)}")
        print("\nAnalyzing code with Groq AI...\n")

        report = review_code(parsed_data, valid_lines)

        output_file = (
            ARTIFACTS / f"pr_{pr_number}_bug_findings.json"
        )

        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=4)

        print("SUCCESS! Bug review completed.")
        print(f"Findings detected: {report['total_findings']}")

        for finding in report["findings"]:
            print(
                f"\n[{finding['severity']}] "
                f"{finding['filename']}:"
                f"{finding['line_number']}"
            )
            print(f"Issue: {finding['title']}")
            print(f"Confidence: {finding['confidence']}")

        print(f"\nResults saved at: {output_file}")

    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()


