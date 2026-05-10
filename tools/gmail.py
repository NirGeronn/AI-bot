import json
import base64
import email
from email.mime.text import MIMEText
from datetime import datetime
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_TOKEN_PATH

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

GMAIL_TOOLS = [
    {
        "name": "gmail_check_inbox",
        "description": "Check recent emails in the Gmail inbox. Returns subject, sender, date, and snippet for each email.",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "description": "Number of emails to fetch (default 5, max 20)",
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "Only show unread emails (default false)",
                },
            },
        },
    },
    {
        "name": "gmail_search",
        "description": "Search emails using Gmail search syntax (same as the Gmail search bar). Examples: 'from:john', 'subject:invoice', 'is:unread', 'after:2024/01/01'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Number of results (default 5, max 20)",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "gmail_read_email",
        "description": "Read the full content of a specific email by its ID. Use gmail_check_inbox or gmail_search first to get email IDs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {
                    "type": "string",
                    "description": "The email ID to read",
                },
            },
            "required": ["email_id"],
        },
    },
    {
        "name": "gmail_send",
        "description": "Send an email via Gmail.",
        "input_schema": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject",
                },
                "body": {
                    "type": "string",
                    "description": "Email body (plain text)",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
]


def _get_gmail_service():
    """Get authenticated Gmail service, refreshing token if needed."""
    creds = None

    try:
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, SCOPES)
    except (FileNotFoundError, ValueError):
        pass

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        _save_token(creds)
    elif not creds or not creds.valid:
        raise RuntimeError(
            "Gmail not authenticated. Run 'python auth_gmail.py' on a machine with a browser to set up authentication."
        )

    return build("gmail", "v1", credentials=creds)


def _save_token(creds):
    with open(GOOGLE_TOKEN_PATH, "w") as f:
        f.write(creds.to_json())


def _parse_headers(headers, keys):
    result = {}
    for h in headers:
        if h["name"].lower() in keys:
            result[h["name"].lower()] = h["value"]
    return result


async def execute_gmail_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        service = _get_gmail_service()
    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    if name == "gmail_check_inbox":
        max_results = min(input_data.get("max_results", 5), 20)
        query = "in:inbox"
        if input_data.get("unread_only"):
            query += " is:unread"

        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = _parse_headers(detail.get("payload", {}).get("headers", []),
                                     {"from", "subject", "date"})
            emails.append({
                "id": msg["id"],
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "snippet": detail.get("snippet", ""),
                "unread": "UNREAD" in detail.get("labelIds", []),
            })
        return json.dumps({"emails": emails})

    elif name == "gmail_search":
        query = input_data["query"]
        max_results = min(input_data.get("max_results", 5), 20)

        results = service.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()

        messages = results.get("messages", [])
        emails = []
        for msg in messages:
            detail = service.users().messages().get(
                userId="me", id=msg["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()
            headers = _parse_headers(detail.get("payload", {}).get("headers", []),
                                     {"from", "subject", "date"})
            emails.append({
                "id": msg["id"],
                "from": headers.get("from", ""),
                "subject": headers.get("subject", ""),
                "date": headers.get("date", ""),
                "snippet": detail.get("snippet", ""),
            })
        return json.dumps({"emails": emails})

    elif name == "gmail_read_email":
        email_id = input_data["email_id"]
        detail = service.users().messages().get(
            userId="me", id=email_id, format="full"
        ).execute()

        headers = _parse_headers(detail.get("payload", {}).get("headers", []),
                                 {"from", "to", "subject", "date"})

        # Extract body
        body = _extract_body(detail.get("payload", {}))

        return json.dumps({
            "from": headers.get("from", ""),
            "to": headers.get("to", ""),
            "subject": headers.get("subject", ""),
            "date": headers.get("date", ""),
            "body": body[:3000],  # limit size
        })

    elif name == "gmail_send":
        message = MIMEText(input_data["body"])
        message["to"] = input_data["to"]
        message["subject"] = input_data["subject"]

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        sent = service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        return json.dumps({"status": "sent", "id": sent["id"]})

    return json.dumps({"error": f"Unknown gmail tool: {name}"})


def _extract_body(payload):
    """Recursively extract plain text body from email payload."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    # Fallback: try body data directly
    if payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    return "(could not extract email body)"
