
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

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
            f"Parsed PR file not found: {input_file}"
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

            if isinstance(line_number, int):
                valid_lines[(filename, line_number)] = (
                    line.get("code", "")
                )

    return valid_lines


def get_standard_severity(finding):
    """
    Apply consistent severity to known security vulnerabilities.
    """

    issue_text = " ".join([
        str(finding.get("issue_type", "")),
        str(finding.get("title", "")),
        str(finding.get("explanation", ""))
    ]).lower()

    high_risk_indicators = [
        "sql injection",
        "command injection",
        "hardcoded password",
        "hardcoded secret",
        "hardcoded api key",
        "hardcoded credentials",
        "remote code execution"
    ]

    if any(
        indicator in issue_text
        for indicator in high_risk_indicators
    ):
        return "HIGH"

    return None


def review_security(parsed_data, valid_lines):
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    if not api_key:
        raise ValueError("GROQ_API_KEY is missing from .env.")

    client = Groq(api_key=api_key)

    prompt = f"""
You are an expert application security reviewer.

Analyze the changed code for genuine security vulnerabilities.

Focus on:
1. SQL injection.
2. Hardcoded passwords, API keys and secrets.
3. Insecure authentication or authorization.
4. Unsafe handling of user input.
5. Sensitive information exposure.
6. Insecure file handling.
7. Command injection.
8. Other serious application security weaknesses.

SEVERITY POLICY:

- SQL injection: HIGH.
- Command injection: HIGH.
- Hardcoded passwords, API keys and credentials: HIGH.
- Remote code execution: HIGH.
- Other vulnerabilities: Classify according to actual impact.

Severity definitions:
- CRITICAL: Extremely severe vulnerability with major
  security impact.
- HIGH: Serious vulnerability that could compromise
  application security or sensitive data.
- MEDIUM: Security weakness with limited or conditional impact.
- LOW: Minor security weakness with low impact.

Rules:
- Report only genuine security issues supported by code.
- Do not invent vulnerabilities.
- Do not report ordinary programming bugs unless they
  create a security risk.
- Use exact filenames and line numbers from added lines.
- Do not report lines that were not added in this PR.
- Explain the security impact clearly.
- Suggest a practical fix.
- Avoid duplicate findings.
- Follow the severity policy consistently.

Return ONLY valid JSON in this format:

{{
    "overall_summary": "Short security review summary",
    "findings": [
        {{
            "filename": "sample.py",
            "line_number": 3,
            "issue_type": "SQL Injection",
            "severity": "HIGH",
            "title": "Possible SQL injection",
            "explanation": "User-controlled data is directly combined with an SQL query.",
            "suggested_fix": "Use parameterized SQL queries.",
            "confidence": 0.98
        }}
    ]
}}

Severity must be one of:
CRITICAL, HIGH, MEDIUM, LOW.

Confidence must be between 0 and 1.

If no security vulnerabilities are found, return an empty findings array.

Changed code:
{json.dumps(parsed_data, indent=2)}
"""

    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful application security reviewer. "
                    "Follow the severity policy and report only "
                    "evidence-based vulnerabilities."
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
        raise ValueError("Invalid security findings format.")

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
            finding.get("issue_type", "Security Vulnerability")
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
                finding.get("title", "Security vulnerability")
            ),
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
            result.get("overall_summary", "Security review completed.")
        ),
        "total_findings": len(validated_findings),
        "findings": validated_findings
    }


def main():
    pr_number = sys.argv[1] if len(sys.argv) > 1 else "1"

    print(f"\nSecurity Checker reviewing PR #{pr_number}...\n")

    try:
        parsed_data = load_parsed_data(pr_number)

        if not parsed_data:
            print("No changed files found.")
            return

        valid_lines = get_added_lines(parsed_data)

        print(f"Changed files: {len(parsed_data)}")
        print(f"Added lines available for review: {len(valid_lines)}")
        print("\nAnalyzing security with Groq AI...\n")

        report = review_security(parsed_data, valid_lines)

        output_file = (
            ARTIFACTS / f"pr_{pr_number}_security_findings.json"
        )

        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=4)

        print("SUCCESS! Security review completed.")
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


