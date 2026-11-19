
import os
from pathlib import Path
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

token = os.getenv("GITHUB_TOKEN")

if not token:
    print("ERROR: GitHub token not found!")
    raise SystemExit(1)

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json"
}

try:
    response = requests.get(
        "https://api.github.com/user",
        headers=headers,
        timeout=20
    )

    if response.status_code == 200:
        user = response.json()
        print("GitHub authentication successful!")
        print("Authenticated account:", user["login"])

    elif response.status_code == 401:
        print("ERROR: Invalid or expired GitHub token.")

    else:
        print("GitHub API error:", response.status_code)
        print(response.text)

except requests.exceptions.RequestException as error:
    print("Connection error:", error)
