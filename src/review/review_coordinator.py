
import json
import re
import sys
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

SEVERITY_WEIGHT = {
    "CRITICAL": 40,
    "HIGH": 25,
    "MEDIUM": 12,
    "LOW": 4
}

SEVERITY_ORDER = {
    "CRITICAL": 4,
    "HIGH": 3,
    "MEDIUM": 2,
    "LOW": 1
}


def load_findings(filename):
    path = ARTIFACTS / filename

    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        return data.get("findings", [])

    if isinstance(data, list):
        return data

    return []


def normalize_issue(title, issue_type):
    """
    Identify different descriptions of the same issue.
    """

    text = f"{issue_type} {title}".lower()

    # Normalize standard and Unicode hyphens.
    text = re.sub(r"[-‐‑‒–—_]+", " ", text)

    # Normalize spaces.
    text = re.sub(r"\s+", " ", text).strip()

    aliases = {
        "sql injection": [
            "sql injection"
        ],
        "division by zero": [
            "division by zero",
            "zero division",
            "zero denominator"
        ],
        "command injection": [
            "command injection"
        ],
        "hardcoded secret": [
            "hardcoded secret",
            "hard coded secret",
            "hardcoded password",
            "hardcoded api key"
        ],
        "path traversal": [
            "path traversal",
            "directory traversal"
        ],
        "unsafe deserialization": [
            "unsafe deserialization",
            "insecure deserialization"
        ],
        "cross site scripting": [
            "cross site scripting",
            "xss"
        ],
        "missing database error handling": [
            "database error handling",
            "database exception handling",
            "uncaught database exception"
        ]
    }

    for canonical_name, phrases in aliases.items():
        if any(phrase in text for phrase in phrases):
            return canonical_name

    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def combine_findings(agent_results):
    grouped = {}

    for agent_name, findings in agent_results.items():

        for finding in findings:

            if not isinstance(finding, dict):
                continue

            filename = finding.get("filename", "unknown")
            line_number = finding.get("line_number")

            if not isinstance(line_number, int):
                continue

            title = finding.get("title", "Code issue")
            issue_type = finding.get("issue_type", "General")

            issue_key = normalize_issue(title, issue_type)

            # Same file, line and issue category = duplicate.
            key = (filename, line_number, issue_key)

            severity = str(
                finding.get("severity", "LOW")
            ).upper()

            if severity not in SEVERITY_ORDER:
                severity = "LOW"

            try:
                confidence = float(
                    finding.get("confidence", 0.5)
                )
            except (TypeError, ValueError):
                confidence = 0.5

            confidence = max(0.0, min(1.0, confidence))

            explanation = finding.get("explanation", "")
            suggested_fix = finding.get("suggested_fix", "")

            current = {
                "filename": filename,
                "line_number": line_number,
                "issue_type": issue_type,
                "issue_key": issue_key,
                "severity": severity,
                "title": title,
                "explanation": explanation,
                "suggested_fix": suggested_fix,
                "confidence": confidence,
                "agents": [agent_name]
            }

            if key not in grouped:
                grouped[key] = current

            else:
                existing = grouped[key]

                # Keep the highest severity.
                if (
                    SEVERITY_ORDER[severity]
                    > SEVERITY_ORDER[existing["severity"]]
                ):
                    existing["severity"] = severity

                # Keep the highest confidence.
                existing["confidence"] = max(
                    existing["confidence"],
                    confidence
                )

                # Combine the agent names.
                if agent_name not in existing["agents"]:
                    existing["agents"].append(agent_name)

                # Keep the most detailed explanation.
                if len(explanation) > len(existing["explanation"]):
                    existing["explanation"] = explanation

                # Keep the most detailed suggested fix.
                if len(suggested_fix) > len(existing["suggested_fix"]):
                    existing["suggested_fix"] = suggested_fix

    results = list(grouped.values())

    results.sort(
        key=lambda item: (
            -SEVERITY_ORDER[item["severity"]],
            item["filename"],
            item["line_number"]
        )
    )

    return results


def calculate_risk(findings):
    score = 0

    for finding in findings:
        weight = SEVERITY_WEIGHT[finding["severity"]]
        confidence = finding["confidence"]

        score += weight * confidence

    score = min(100, round(score))

    if any(
        finding["severity"] == "CRITICAL"
        for finding in findings
    ):
        level = "CRITICAL"

    elif any(
        finding["severity"] == "HIGH"
        for finding in findings
    ):
        level = "HIGH"

    elif any(
        finding["severity"] == "MEDIUM"
        for finding in findings
    ):
        level = "MEDIUM"

    else:
        level = "LOW"

    return score, level


def generate_summary(findings, score, level):
    counts = defaultdict(int)

    for finding in findings:
        counts[finding["severity"]] += 1

    lines = [
        "# Pull Request Review",
        "",
        f"**Risk score:** {score}/100",
        f"**Risk level:** {level}",
        "",
        "## Findings",
        "",
        f"- Total unique findings: {len(findings)}",
        f"- Critical: {counts['CRITICAL']}",
        f"- High: {counts['HIGH']}",
        f"- Medium: {counts['MEDIUM']}",
        f"- Low: {counts['LOW']}",
        "",
        "## Details",
        ""
    ]

    if not findings:
        lines.append("No actionable issues were reported.")

    for finding in findings:
        lines.extend([
            f"### [{finding['severity']}] {finding['title']}",
            "",
            f"- **File:** `{finding['filename']}`",
            f"- **Line:** {finding['line_number']}",
            f"- **Detected by:** {', '.join(finding['agents'])}",
            f"- **Confidence:** {finding['confidence']:.0%}",
            f"- **Explanation:** {finding['explanation']}",
            f"- **Suggested fix:** {finding['suggested_fix']}",
            ""
        ])

    return "\n".join(lines)


def main():
    pr_number = sys.argv[1] if len(sys.argv) > 1 else "1"

    input_files = {
        "Bug Finder": f"pr_{pr_number}_bug_findings.json",
        "Security Checker": f"pr_{pr_number}_security_findings.json",
        "Style Reviewer": f"pr_{pr_number}_style_findings.json"
    }

    print("\nCombining AI review results...\n")

    agent_results = {}

    for agent_name, filename in input_files.items():

        findings = load_findings(filename)

        if findings is None:
            print(f"MISSING: {filename}")
            print(f"Run the {agent_name} first.")
            return

        agent_results[agent_name] = findings

        print(f"{agent_name}: {len(findings)} finding(s)")

    combined = combine_findings(agent_results)

    score, level = calculate_risk(combined)

    summary = generate_summary(
        combined,
        score,
        level
    )

    report = {
        "pull_request": int(pr_number),
        "total_findings": len(combined),
        "risk_score": score,
        "risk_level": level,
        "findings": combined
    }

    report_path = ARTIFACTS / f"pr_{pr_number}_review_report.json"
    summary_path = ARTIFACTS / f"pr_{pr_number}_review_summary.md"

    with open(report_path, "w", encoding="utf-8") as file:
        json.dump(report, file, indent=4)

    with open(summary_path, "w", encoding="utf-8") as file:
        file.write(summary)

    print("\nSUCCESS! Review coordination completed.")
    print(f"Total unique findings: {len(combined)}")
    print(f"Risk score: {score}/100")
    print(f"Risk level: {level}")

    print(f"\nReport saved: {report_path}")
    print(f"Summary saved: {summary_path}")


if __name__ == "__main__":
    main()


