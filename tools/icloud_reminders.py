import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import caldav
from config import USER_TIMEZONE

ICLOUD_CALDAV_URL = "https://caldav.icloud.com"

ICLOUD_REMINDER_TOOLS = [
    {
        "name": "icloud_list_reminder_lists",
        "description": "List all iCloud Reminder lists (e.g. 'Reminders', 'Shopping', 'Work'). Use this to find the list_id for other reminder tools.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "icloud_list_reminders",
        "description": "List reminders from iCloud Reminders. Can show incomplete, completed, or all reminders from a specific list or all lists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {
                    "type": "string",
                    "description": "Reminder list URL/ID or name from icloud_list_reminder_lists. If omitted, searches all lists.",
                },
                "include_completed": {
                    "type": "boolean",
                    "description": "Include completed reminders (default false — only shows incomplete)",
                },
            },
        },
    },
    {
        "name": "icloud_create_reminder",
        "description": "Create a new reminder in iCloud Reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_id": {
                    "type": "string",
                    "description": "Reminder list URL/ID or name. If omitted, uses the default list.",
                },
                "title": {
                    "type": "string",
                    "description": "Reminder title",
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional due date in ISO 8601 format, e.g. '2025-03-15' or '2025-03-15T10:00:00'",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes / description",
                },
                "priority": {
                    "type": "integer",
                    "description": "Priority: 1 (high), 5 (medium), 9 (low), 0 (none). Default: 0",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "icloud_complete_reminder",
        "description": "Mark an iCloud reminder as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The reminder UID or URL to mark as completed",
                },
            },
            "required": ["reminder_id"],
        },
    },
    {
        "name": "icloud_delete_reminder",
        "description": "Delete a reminder from iCloud Reminders.",
        "input_schema": {
            "type": "object",
            "properties": {
                "reminder_id": {
                    "type": "string",
                    "description": "The reminder UID or URL to delete",
                },
            },
            "required": ["reminder_id"],
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
            "iCloud not configured. Set ICLOUD_EMAIL and ICLOUD_APP_PASSWORD environment variables. "
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


def _get_reminder_lists(principal):
    """Get calendars that support VTODO (reminder lists)."""
    lists = []
    for cal in principal.calendars():
        # Try to identify reminder lists by checking supported components
        # iCloud reminder lists support VTODO
        try:
            props = cal.get_properties([caldav.dav.DisplayName()])
            name = cal.name or "(unnamed)"
            lists.append(cal)
        except Exception:
            lists.append(cal)
    return lists


def _find_reminder_list(principal, list_id=None):
    """Find a specific reminder list by URL or name, or return the first one."""
    calendars = principal.calendars()
    if not calendars:
        raise RuntimeError("No calendars/reminder lists found in iCloud account.")
    if list_id:
        for cal in calendars:
            if str(cal.url) == list_id or cal.name == list_id:
                return cal
        raise RuntimeError(f"Reminder list not found: {list_id}")
    # Return first calendar (often the default Reminders list)
    return calendars[0]


def _parse_vtodo(vtodo):
    """Parse a VTODO component into a clean dict."""
    tz = ZoneInfo(USER_TIMEZONE)

    def _dt_str(dt_val):
        if dt_val is None:
            return ""
        if isinstance(dt_val, datetime):
            if dt_val.tzinfo:
                dt_val = dt_val.astimezone(tz)
            return dt_val.isoformat()
        return str(dt_val)

    try:
        due = vtodo.get("due")
        due_val = due.dt if due else None
    except Exception:
        due_val = None

    try:
        completed = vtodo.get("completed")
        completed_val = completed.dt if completed else None
    except Exception:
        completed_val = None

    status = str(vtodo.get("status", ""))
    is_completed = status.upper() == "COMPLETED" or completed_val is not None

    priority_val = 0
    try:
        priority_val = int(str(vtodo.get("priority", 0)))
    except (ValueError, TypeError):
        pass

    priority_label = {1: "high", 5: "medium", 9: "low"}.get(priority_val, "none")

    return {
        "id": str(vtodo.get("uid", "")),
        "title": str(vtodo.get("summary", "(no title)")),
        "notes": str(vtodo.get("description", "")),
        "due": _dt_str(due_val),
        "completed": is_completed,
        "completed_date": _dt_str(completed_val),
        "priority": priority_label,
        "status": status,
    }


def _parse_todo_from_caldav(todo):
    """Parse a caldav todo object."""
    try:
        vtodos = todo.icalendar_instance.walk("VTODO")
        if vtodos:
            result = _parse_vtodo(vtodos[0])
            result["todo_url"] = str(todo.url)
            return result
    except Exception as e:
        return {"error": str(e), "todo_url": str(todo.url)}
    return {"error": "Could not parse reminder", "todo_url": str(todo.url)}


def _find_todo_by_id(principal, reminder_id):
    """Find a todo object by UID or URL across all calendars."""
    for cal in principal.calendars():
        try:
            todos = cal.todos(include_completed=True)
            for todo in todos:
                if str(todo.url) == reminder_id:
                    return todo
                parsed = _parse_todo_from_caldav(todo)
                if parsed.get("id") == reminder_id:
                    return todo
        except Exception:
            continue
    return None


async def execute_icloud_reminder_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        principal = _get_principal()
    except RuntimeError as e:
        return json.dumps({"error": str(e)})
    except Exception as e:
        return json.dumps({"error": f"iCloud connection failed: {str(e)}"})

    if name == "icloud_list_reminder_lists":
        calendars = principal.calendars()
        result = []
        for cal in calendars:
            # Check if this calendar has todos
            try:
                todos = cal.todos(include_completed=False)
                has_reminders = True
                count = len(todos)
            except Exception:
                has_reminders = False
                count = 0

            if has_reminders:
                result.append({
                    "id": str(cal.url),
                    "name": cal.name or "(unnamed)",
                    "incomplete_count": count,
                })
        if not result:
            # If filtering didn't work, return all calendars
            for cal in calendars:
                result.append({
                    "id": str(cal.url),
                    "name": cal.name or "(unnamed)",
                })
        return json.dumps({"reminder_lists": result})

    elif name == "icloud_list_reminders":
        list_id = input_data.get("list_id")
        include_completed = input_data.get("include_completed", False)

        if list_id:
            calendars = [_find_reminder_list(principal, list_id)]
        else:
            calendars = principal.calendars()

        all_reminders = []
        for cal in calendars:
            try:
                todos = cal.todos(include_completed=include_completed)
                for todo in todos:
                    parsed = _parse_todo_from_caldav(todo)
                    if not include_completed and parsed.get("completed"):
                        continue
                    parsed["list"] = cal.name or "(unnamed)"
                    all_reminders.append(parsed)
            except Exception as e:
                # Calendar might not support VTODO, skip it
                continue

        # Sort: incomplete first, then by due date
        def sort_key(r):
            completed = "1" if r.get("completed") else "0"
            due = r.get("due", "") or "9999"
            return (completed, due)
        all_reminders.sort(key=sort_key)

        return json.dumps({"reminders": all_reminders, "count": len(all_reminders)})

    elif name == "icloud_create_reminder":
        list_id = input_data.get("list_id")
        cal = _find_reminder_list(principal, list_id)

        title = input_data["title"]
        due_date = input_data.get("due_date", "")
        notes = input_data.get("notes", "")
        priority = input_data.get("priority", 0)
        uid = str(uuid.uuid4())

        tz = ZoneInfo(USER_TIMEZONE)

        vcal = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "PRODID:-//AI Bot//EN\r\n"
            "BEGIN:VTODO\r\n"
            f"UID:{uid}\r\n"
            f"SUMMARY:{title}\r\n"
            f"STATUS:NEEDS-ACTION\r\n"
        )

        if due_date:
            if "T" in due_date:
                dt = datetime.fromisoformat(due_date)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                vcal += f"DUE:{dt.strftime('%Y%m%dT%H%M%S')}\r\n"
            else:
                vcal += f"DUE;VALUE=DATE:{due_date.replace('-', '')}\r\n"

        if notes:
            vcal += f"DESCRIPTION:{notes}\r\n"
        if priority:
            vcal += f"PRIORITY:{priority}\r\n"

        vcal += "END:VTODO\r\nEND:VCALENDAR\r\n"

        todo = cal.save_todo(vcal)
        return json.dumps({
            "status": "created",
            "title": title,
            "list": cal.name or "(default)",
            "id": uid,
            "todo_url": str(todo.url),
        })

    elif name == "icloud_complete_reminder":
        reminder_id = input_data["reminder_id"]
        todo = _find_todo_by_id(principal, reminder_id)
        if not todo:
            return json.dumps({"error": f"Reminder not found: {reminder_id}"})

        todo.complete()
        return json.dumps({"status": "completed", "reminder_id": reminder_id})

    elif name == "icloud_delete_reminder":
        reminder_id = input_data["reminder_id"]
        todo = _find_todo_by_id(principal, reminder_id)
        if not todo:
            return json.dumps({"error": f"Reminder not found: {reminder_id}"})

        todo.delete()
        return json.dumps({"status": "deleted", "reminder_id": reminder_id})

    return json.dumps({"error": f"Unknown reminder tool: {name}"})
