
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"


def parse_diff(diff_text):
    files = []
    current_file = None

    old_line_number = 0
    new_line_number = 0
    inside_hunk = False

    for line in diff_text.splitlines():

        # Detect the beginning of a new file.
        if line.startswith("diff --git "):
            if current_file is not None:
                files.append(current_file)

            current_file = None
            inside_hunk = False
            continue

        # Get the new filename.
        if line.startswith("+++ b/"):
            filename = line[6:]

            current_file = {
                "filename": filename,
                "additions": 0,
                "deletions": 0,
                "added_lines": [],
                "deleted_lines": []
            }
            continue

        if line.startswith("+++ ") or line.startswith("--- "):
            continue

        # Read the line numbers from a diff hunk.
        if line.startswith("@@"):
            try:
                header = line.split("@@")[1].strip()

                old_part, new_part = header.split()

                old_line_number = int(
                    old_part.split(",")[0].lstrip("-")
                )

                new_line_number = int(
                    new_part.split(",")[0].lstrip("+")
                )

                inside_hunk = True

            except (ValueError, IndexError):
                inside_hunk = False

            continue

        if current_file is None or not inside_hunk:
            continue

        # Ignore diff metadata.
        if line.startswith("\\"):
            continue

        # Added line.
        if line.startswith("+"):
            current_file["added_lines"].append({
                "line_number": new_line_number,
                "code": line[1:]
            })

            current_file["additions"] += 1
            new_line_number += 1

        # Deleted line.
        elif line.startswith("-"):
            current_file["deleted_lines"].append({
                "line_number": old_line_number,
                "code": line[1:]
            })

            current_file["deletions"] += 1
            old_line_number += 1

        # Unchanged line.
        elif line.startswith(" "):
            old_line_number += 1
            new_line_number += 1

    if current_file is not None:
        files.append(current_file)

    return files


def main():
    pr_number = sys.argv[1] if len(sys.argv) > 1 else "1"

    diff_path = ARTIFACTS / f"pr_{pr_number}.diff"

    if not diff_path.exists():
        print(f"ERROR: Diff file not found: {diff_path}")
        print("Run the GitHub diff fetcher first.")
        return

    print(f"\nParsing Pull Request #{pr_number} diff...\n")

    with open(diff_path, "r", encoding="utf-8") as file:
        diff_text = file.read()

    parsed_files = parse_diff(diff_text)

    total_additions = sum(
        item["additions"] for item in parsed_files
    )

    total_deletions = sum(
        item["deletions"] for item in parsed_files
    )

    output_path = ARTIFACTS / f"pr_{pr_number}_parsed.json"

    with open(output_path, "w", encoding="utf-8") as file:
        json.dump(parsed_files, file, indent=4)

    print("SUCCESS! Diff parsed successfully.")
    print(f"Pull Request: #{pr_number}")
    print(f"Files found: {len(parsed_files)}")
    print(f"Total additions: {total_additions}")
    print(f"Total deletions: {total_deletions}")

    for item in parsed_files:
        print(f"\nFile: {item['filename']}")
        print(f"Additions: {item['additions']}")
        print(f"Deletions: {item['deletions']}")

        print("\nAdded code:")

        for added_line in item["added_lines"]:
            print(
                f"Line {added_line['line_number']}: "
                f"{added_line['code']}"
            )

    print(f"\nParsed data saved at: {output_path}")


if __name__ == "__main__":
    main()

