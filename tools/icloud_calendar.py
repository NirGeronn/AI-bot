import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import caldav
from config import USER_TIMEZONE

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"

CALENDAR_TOOLS = [
    {
        "name": "calendar_list_calendars",
        "description": "List all available iCloud Calendars. Use this first to find the calendar_id for specific calendars.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "calendar_list_events",
        "description": "List upcoming events from iCloud Calendar. Can query any calendar by providing the calendar_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar URL/ID from calendar_list_calendars. If omitted, searches all calendars.",
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
        "description": "Get full details of a specific calendar event by its ID (URL).",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The event URL/ID to look up",
                },
            },
            "required": ["event_id"],
        },
    },
    {
        "name": "calendar_create_event",
        "description": "Create a new event on iCloud Calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "calendar_id": {
                    "type": "string",
                    "description": "Calendar URL/ID to create the event on. If omitted, uses the first/default calendar.",
                },
                "title": {
                    "type": "string",
                    "description": "Event title / summary",
                },
                "start": {
                    "type": "string",
                    "description": "Start date-time in ISO 8601 format, e.g. '2025-03-15T10:00:00'. For all-day events use date only: '2025-03-15'.",
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
        "description": "Delete an event from iCloud Calendar by its ID (URL).",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The event URL/ID to delete",
                },
            },
            "required": ["event_id"],
        },
    },
]


def _get_client():
    """Get authenticated CalDAV client for iCloud."""
    import os
    icloud_email = os.environ.get("ICLOUD_EMAIL", "")
    icloud_password = os.environ.get("ICLOUD_APP_PASSWORD", "")
    if not icloud_email or not icloud_password:
        raise RuntimeError(
            "iCloud Calendar not configured. Set ICLOUD_EMAIL and ICLOUD_APP_PASSWORD environment variables. "
            "Generate an app-specific password at https://appleid.apple.com/account/manage"
        )
    return caldav.DAVClient(
        url=ICLOUD_CALDAV_URL,
        username=icloud_email,
        password=icloud_password,
    )


def _get_principal():
    client = _get_client()
    return client.principal()


def _get_calendar(principal, calendar_id=None):
    """Get a specific calendar or the first one."""
    calendars = principal.calendars()
    if not calendars:
        raise RuntimeError("No calendars found in iCloud account.")
    if calendar_id:
        for cal in calendars:
            if str(cal.url) == calendar_id or cal.name == calendar_id:
                return cal
        raise RuntimeError(f"Calendar not found: {calendar_id}")
    return calendars[0]


def _parse_vevent(vevent):
    """Parse a VEVENT component into a clean dict."""
    tz = ZoneInfo(USER_TIMEZONE)

    def _dt_str(dt_val):
        if dt_val is None:
            return ""
        if isinstance(dt_val, datetime):
            if dt_val.tzinfo:
                dt_val = dt_val.astimezone(tz)
            return dt_val.isoformat()
        # date object (all-day event)
        return str(dt_val)

    try:
        dtstart = vevent.get("dtstart")
        dtend = vevent.get("dtend")
        start_val = dtstart.dt if dtstart else None
        end_val = dtend.dt if dtend else None
    except Exception:
        start_val = None
        end_val = None

    return {
        "id": str(vevent.get("uid", "")),
        "title": str(vevent.get("summary", "(no title)")),
        "start": _dt_str(start_val),
        "end": _dt_str(end_val),
        "location": str(vevent.get("location", "")),
        "description": str(vevent.get("description", ""))[:500],
        "status": str(vevent.get("status", "")),
    }


def _parse_event_from_caldav(event):
    """Parse a caldav event object."""
    try:
        vevents = event.icalendar_instance.walk("VEVENT")
        if vevents:
            result = _parse_vevent(vevents[0])
            result["event_url"] = str(event.url)
            return result
    except Exception as e:
        return {"error": str(e), "event_url": str(event.url)}
    return {"error": "Could not parse event", "event_url": str(event.url)}


async def execute_calendar_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        principal = _get_principal()
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"iCloud connection failed: {str(e)}"})

    if name == "calendar_list_calendars":
        calendars = principal.calendars()
        result = []
        for cal in calendars:
            result.append({
                "id": str(cal.url),
                "name": cal.name or "(unnamed)",
            })
        return json.dumps({"calendars": result})

    elif name == "calendar_list_events":
        calendar_id = input_data.get("calendar_id")
        days_ahead = min(input_data.get("days_ahead", 7), 30)
        max_results = min(input_data.get("max_results", 10), 25)

        tz = ZoneInfo(USER_TIMEZONE)
        now = datetime.now(tz)
        start = now
        end = now + timedelta(days=days_ahead)

        if calendar_id:
            calendars = [_get_calendar(principal, calendar_id)]
        else:
            calendars = principal.calendars()

        all_events = []
        for cal in calendars:
            try:
                events = cal.search(
                    start=start,
                    end=end,
                    event=True,
                    expand=True,
                )
                for ev in events:
                    parsed = _parse_event_from_caldav(ev)
                    parsed["calendar"] = cal.name or "(unnamed)"
                    all_events.append(parsed)
            except Exception as e:
                all_events.append({"error": f"Failed to read {cal.name}: {str(e)}"})

        # Sort by start time
        def sort_key(e):
            s = e.get("start", "")
            return s if s else "9999"
        all_events.sort(key=sort_key)
        all_events = all_events[:max_results]

        return json.dumps({"events": all_events, "count": len(all_events)})

    elif name == "calendar_get_event":
        event_url = input_data["event_id"]
        try:
            client = _get_client()
            event = client.calendar(url=event_url).event_by_url(event_url)
            return json.dumps(_parse_event_from_caldav(event))
        except Exception:
            # Try searching all calendars for this event UID
            for cal in principal.calendars():
                try:
                    events = cal.events()
                    for ev in events:
                        parsed = _parse_event_from_caldav(ev)
                        if parsed.get("id") == event_url or parsed.get("event_url") == event_url:
                            return json.dumps(parsed)
                except Exception:
                    continue
            return json.dumps({"error": f"Event not found: {event_url}"})

    elif name == "calendar_create_event":
        calendar_id = input_data.get("calendar_id")
        cal = _get_calendar(principal, calendar_id)

        title = input_data["title"]
        start_str = input_data["start"]
        end_str = input_data["end"]
        description = input_data.get("description", "")
        location = input_data.get("location", "")

        tz = ZoneInfo(USER_TIMEZONE)
        is_allday = "T" not in start_str

        if is_allday:
            dtstart_str = start_str
            dtend_str = end_str
            vcal = (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//AI Bot//EN\r\n"
                "BEGIN:VEVENT\r\n"
                f"SUMMARY:{title}\r\n"
                f"DTSTART;VALUE=DATE:{start_str.replace('-', '')}\r\n"
                f"DTEND;VALUE=DATE:{end_str.replace('-', '')}\r\n"
            )
        else:
            dt_start = datetime.fromisoformat(start_str)
            dt_end = datetime.fromisoformat(end_str)
            if dt_start.tzinfo is None:
                dt_start = dt_start.replace(tzinfo=tz)
            if dt_end.tzinfo is None:
                dt_end = dt_end.replace(tzinfo=tz)
            vcal = (
                "BEGIN:VCALENDAR\r\n"
                "VERSION:2.0\r\n"
                "PRODID:-//AI Bot//EN\r\n"
                "BEGIN:VEVENT\r\n"
                f"SUMMARY:{title}\r\n"
                f"DTSTART:{dt_start.strftime('%Y%m%dT%H%M%S')}\r\n"
                f"DTEND:{dt_end.strftime('%Y%m%dT%H%M%S')}\r\n"
            )

        if description:
            vcal += f"DESCRIPTION:{description}\r\n"
        if location:
            vcal += f"LOCATION:{location}\r\n"
        vcal += "END:VEVENT\r\nEND:VCALENDAR\r\n"

        event = cal.save_event(vcal)
        return json.dumps({
            "status": "created",
            "title": title,
            "calendar": cal.name or "(default)",
            "event_url": str(event.url),
        })

    elif name == "calendar_delete_event":
        event_url = input_data["event_id"]
        try:
            client = _get_client()
            event = client.calendar(url=event_url).event_by_url(event_url)
            event.delete()
            return json.dumps({"status": "deleted", "event_url": event_url})
        except Exception:
            # Search all calendars
            for cal in principal.calendars():
                try:
                    events = cal.events()
                    for ev in events:
                        if str(ev.url) == event_url:
                            ev.delete()
                            return json.dumps({"status": "deleted", "event_url": event_url})
                        parsed = _parse_event_from_caldav(ev)
                        if parsed.get("id") == event_url:
                            ev.delete()
                            return json.dumps({"status": "deleted", "event_id": event_url})
                except Exception:
                    continue
            return json.dumps({"error": f"Event not found for deletion: {event_url}"})

    return json.dumps({"error": f"Unknown calendar tool: {name}"})
