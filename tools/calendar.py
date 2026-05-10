import json
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import GOOGLE_TOKEN_PATH

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
]

CALENDAR_TOOLS = [
    {
        "name": "calendar_list_calendars",
        "description": "List all available Google Calendars (personal, work, shared, etc.). Use this first to find the calendar_id for the user's work or other calendars.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "calendar_list_events",
        "description": "List upcoming events from Google Calendar. Can query any calendar (personal, work, etc.) by providing the calendar_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to query. Use 'primary' for personal calendar, or the email/ID from calendar_list_calendars for other calendars (e.g. work). Default: 'primary'.",
                },
                "days_ahead": {
                    "type": "integer",
                    "description": "How many days ahead to look (default 7, max 30)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max number of events to return (default 10, max 25)",
                },
            },
        },
    },
    {
        "name": "calendar_get_event",
        "description": "Get full details of a specific calendar event by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Default: 'primary'.",
                },
                "event_id": {
                    "type": "string",
                    "description": "The event ID to look up",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Create a new event on Google Calendar. Can create on any calendar (personal, work, etc.).",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID to create the event on. Default: 'primary'.",
                },
                "title": {
                    "type": "string",
                    "description": "Event title / summary",
                },
                "start": {
                    "type": "string",
                    "description": "Start date-time in ISO 8601 format, e.g. '2025-03-15T10:00:00+03:00'. For all-day events use date only: '2025-03-15'.",
                },
                "end": {
                    "type": "string",
                    "description": "End date-time in ISO 8601 format. For all-day events use the next date: '2025-03-16'.",
                },
                "description": {
                    "type": "string",
                    "description": "Optional event description / notes",
                },
                "location": {
                    "type": "string",
                    "description": "Optional event location",
                },
            },
            "required": ["title", "start", "end"],
        },
    },
    {
        "name": "calendar_delete_event",
        "description": "Delete an event from Google Calendar by its ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar ID. Default: 'primary'.",
                },
                "event_id": {
                    "type": "string",
                    "description": "The event ID to delete",
                },
            },
            "required": ["event_id"],
        },
    },
]


def _get_calendar_service():
    """Get authenticated Google Calendar service, refreshing token if needed."""
    creds = None

    try:
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, SCOPES)
    except (FileNotFoundError, ValueError):
        pass

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(GOOGLE_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
    elif not creds or not creds.valid:
        raise RuntimeError(
            "Google Calendar not authenticated. Run 'python auth_gmail.py' to set up authentication (it now includes Calendar scopes)."
        )

    return build("calendar", "v3", credentials=creds)


def _format_event(event):
    """Format a calendar event into a clean dict."""
    start = event.get("start", {})
    end = event.get("end", {})
    return {
        "id": event.get("id", ""),
        "title": event.get("summary", "(no title)"),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
        "location": event.get("location", ""),
        "description": (event.get("description", "") or "")[:500],
        "status": event.get("status", ""),
        "calendar": event.get("organizer", {}).get("displayName", ""),
        "html_link": event.get("htmlLink", ""),
    }


async def execute_calendar_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        service = _get_calendar_service()
    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    if name == "calendar_list_calendars":
        result = service.calendarList().list().execute()
        calendars = []
        for cal in result.get("items", []):
            calendars.append({
                "id": cal.get("id", ""),
                "name": cal.get("summary", ""),
                "description": cal.get("description", ""),
                "primary": cal.get("primary", False),
                "access_role": cal.get("accessRole", ""),
            })
        return json.dumps({"calendars": calendars})

    elif name == "calendar_list_events":
        cal_id = input_data.get("calendar_id", "primary")
        days_ahead = min(input_data.get("days_ahead", 7), 30)
        max_results = min(input_data.get("max_results", 10), 25)

        now = datetime.utcnow()
        time_min = now.isoformat() + "Z"
        time_max = (now + timedelta(days=days_ahead)).isoformat() + "Z"

        result = service.events().list(
            calendarId=cal_id,
            timeMin=time_min,
            timeMax=time_max,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        events = [_format_event(e) for e in result.get("items", [])]
        return json.dumps({"calendar_id": cal_id, "events": events, "count": len(events)})

    elif name == "calendar_get_event":
        cal_id = input_data.get("calendar_id", "primary")
        event_id = input_data["event_id"]
        event = service.events().get(
            calendarId=cal_id, eventId=event_id
        ).execute()
        return json.dumps(_format_event(event))

    elif name == "calendar_create_event":
        cal_id = input_data.get("calendar_id", "primary")
        body = {"summary": input_data["title"]}

        start_str = input_data["start"]
        end_str = input_data["end"]

        # Detect all-day events (date only, no 'T')
        if "T" in start_str:
            body["start"] = {"dateTime": start_str}
            body["end"] = {"dateTime": end_str}
        else:
            body["start"] = {"date": start_str}
            body["end"] = {"date": end_str}

        if input_data.get("description"):
            body["description"] = input_data["description"]
        if input_data.get("location"):
            body["location"] = input_data["location"]

        event = service.events().insert(calendarId=cal_id, body=body).execute()
        return json.dumps({
            "status": "created",
            "id": event.get("id"),
            "title": event.get("summary"),
            "calendar_id": cal_id,
            "html_link": event.get("htmlLink"),
        })

    elif name == "calendar_delete_event":
        cal_id = input_data.get("calendar_id", "primary")
        event_id = input_data["event_id"]
        service.events().delete(calendarId=cal_id, eventId=event_id).execute()
        return json.dumps({"status": "deleted", "event_id": event_id, "calendar_id": cal_id})

    return json.dumps({"error": f"Unknown calendar tool: {name}"})
