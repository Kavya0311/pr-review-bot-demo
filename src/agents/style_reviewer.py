
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from groq import Groq

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

load_dotenv(ROOT / ".env")


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


def review_style(parsed_data, valid_lines):
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    if not api_key:
        raise ValueError("GROQ_API_KEY is missing from .env.")

    client = Groq(api_key=api_key)

    prompt = f"""
You are an experienced software engineer performing a
code quality and maintainability review of a GitHub Pull Request.

Analyze the changed code for meaningful style and quality problems.

Focus on:
1. Unnecessary temporary variables.
2. Poor variable and function naming.
3. Missing error handling where it is important.
4. Repeated or redundant code.
5. Poor readability and maintainability.
6. Unnecessary complexity.
7. Violations of common coding conventions.

Rules:
- Focus on meaningful improvements, not personal preferences.
- Do not report minor formatting issues.
- Do not report the same issue as a security or bug finding
  unless it is genuinely a separate code-quality problem.
- Do not report division by zero or other runtime bugs.
- Do not invent missing requirements.
- Report only issues on added lines.
- Use exact filenames and line numbers.
- Explain why the code quality should be improved.
- Suggest a practical correction.
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

Severity must be one of:
CRITICAL, HIGH, MEDIUM, LOW.

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
                    "Focus on useful, evidence-based improvements."
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

    allowed_severities = {
        "CRITICAL", "HIGH", "MEDIUM", "LOW"
    }

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
            finding.get("issue_type", "Code Quality")
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
            finding.get("severity", "LOW")
        ).upper()

        if severity not in allowed_severities:
            severity = "LOW"

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

        output_file = (
            ARTIFACTS / f"pr_{pr_number}_style_findings.json"
        )

        with open(output_file, "w", encoding="utf-8") as file:
            json.dump(report, file, indent=4)

        print("SUCCESS! Style review completed.")
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

