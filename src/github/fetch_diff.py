
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"

load_dotenv(ROOT / ".env")


def fetch_pr_diff(owner, repo, pr_number):
    token = os.getenv("GITHUB_TOKEN")

    if not token:
        raise ValueError("GITHUB_TOKEN is missing from .env.")

    url = (
        f"https://api.github.com/repos/"
        f"{owner}/{repo}/pulls/{pr_number}"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github.diff",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    print(f"\nFetching Pull Request #{pr_number} diff...\n")

    response = requests.get(
        url,
        headers=headers,
        timeout=30
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"GitHub API error: {response.status_code}\n"
            f"{response.text}"
        )

    diff_text = response.text

    if not diff_text.strip():
        raise ValueError("The Pull Request diff is empty.")

    ARTIFACTS.mkdir(parents=True, exist_ok=True)

    output_file = ARTIFACTS / f"pr_{pr_number}.diff"

    with open(output_file, "w", encoding="utf-8") as file:
        file.write(diff_text)

    print("SUCCESS! Pull Request diff fetched.")
    print(f"Pull Request: #{pr_number}")
    print(f"Total characters: {len(diff_text)}")
    print(f"Saved at: {output_file}")

    return diff_text


def main():
    if len(sys.argv) != 4:
        print(
            "Usage: python src/github/fetch_diff.py "
            "<owner> <repository> <PR number>"
        )
        sys.exit(1)

    owner = sys.argv[1]
    repo = sys.argv[2]
    pr_number = sys.argv[3]

    if not pr_number.isdigit() or int(pr_number) < 1:
        print("ERROR: PR number must be a positive integer.")
        sys.exit(1)

    try:
        fetch_pr_diff(owner, repo, pr_number)

    except Exception as error:
        print(f"\nERROR: {error}")
        sys.exit(1)


if __name__ == "__main__":
    main()

