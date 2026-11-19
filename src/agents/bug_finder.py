
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


def load_parsed_data(pr_number):
    input_file = ARTIFACTS / f"pr_{pr_number}_parsed.json"

    if not input_file.exists():
        raise FileNotFoundError(
            f"Parsed PR file not found: {input_file}\n"
            "Run the diff parser first."
        )

    with open(input_file, "r", encoding="utf-8") as file:
        data = json.load(file)

    # Support both list and dictionary formats.
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


def review_code(parsed_data, valid_lines):
    api_key = os.getenv("GROQ_API_KEY")
    model = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

    if not api_key:
        raise ValueError("GROQ_API_KEY is missing from your .env file.")

    client = Groq(api_key=api_key)

    prompt = f"""
You are an experienced software engineer performing a
bug-focused review of GitHub Pull Request changes.

Analyze the following changed code carefully.

Your responsibilities:
1. Identify actual programming bugs.
2. Detect incorrect logic and runtime errors.
3. Detect possible division-by-zero errors.
4. Identify unsafe code that can cause application failures.
5. Identify SQL injection when it appears in the changed code.
6. Avoid reporting correct code as a bug.
7. Do not invent problems without evidence.
8. Report only issues associated with the supplied added lines.
9. Do not report formatting or naming suggestions unless they
   create an actual bug.
10. Avoid duplicate findings for the same issue.

IMPORTANT:
- Use the exact filename and line number supplied.
- Only report line numbers present in the added code.
- Give a clear explanation of the problem.
- Suggest a practical correction.

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

    # Validate every finding against actual added lines.
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

        if severity not in allowed_severities:
            severity = "MEDIUM"

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
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
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

