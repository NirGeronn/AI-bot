"""
Run this ONCE on your Mac to authenticate with Gmail and Google Calendar.
It opens a browser for Google OAuth login, then saves the token locally.
The token file is then uploaded to the GCP VM.

Usage:
    python auth_gmail.py                  # saves to default google_token.json
    python auth_gmail.py nehoray_token    # saves to nehoray_token.json (for a different user)
"""
import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/contacts",
    "https://www.googleapis.com/auth/tasks",
]

CLIENT_SECRET_FILE = os.path.join(os.path.dirname(__file__), "client_secret.json")


def main():
    if len(sys.argv) > 1:
        token_name = sys.argv[1]
        if not token_name.endswith(".json"):
            token_name += ".json"
        token_path = os.path.join(os.path.dirname(__file__), token_name)
    else:
        from config import GOOGLE_TOKEN_PATH
        token_path = GOOGLE_TOKEN_PATH

    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRET_FILE, SCOPES)
    creds = flow.run_local_server(port=8090)

    with open(token_path, "w") as f:
        f.write(creds.to_json())

    print(f"Token saved to {token_path}")
    print("You can now upload this to your GCP VM.")


if __name__ == "__main__":
    main()
