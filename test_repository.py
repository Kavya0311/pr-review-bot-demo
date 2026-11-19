
import os
from pathlib import Path
import requests
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(PROJECT_ROOT / ".env")

token = os.getenv("GITHUB_TOKEN")

headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/vnd.github+json"
}

url = "https://api.github.com/repos/Kavya0311/pr-review-bot-demo"

try:
    response = requests.get(
        url,
        headers=headers,
        timeout=20
    )

    if response.status_code == 200:
        repo = response.json()

        print("Repository access successful!")
        print("Repository:", repo["full_name"])
        print(
            "Visibility:",
            "Public" if not repo["private"] else "Private"
        )

    else:
        print("Repository access failed:", response.status_code)
        print(response.text)

except requests.exceptions.RequestException as error:
    print("Connection error:", error)
