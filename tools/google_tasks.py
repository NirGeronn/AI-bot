import json
from datetime import datetime
from zoneinfo import ZoneInfo
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import GOOGLE_TOKEN_PATH, USER_TIMEZONE

SCOPES = ["https://www.googleapis.com/auth/tasks"]

GOOGLE_TASK_TOOLS = [
    {
        "name": "google_list_task_lists",
        "description": "List all Google Tasks lists (e.g. 'My Tasks', 'Work', 'Shopping'). Use this to find the task_list_id for other task tools.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "google_list_tasks",
        "description": "List tasks from a Google Tasks list. Shows incomplete tasks by default.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_list_id": {
                    "type": "string",
                    "description": "Task list ID from google_list_task_lists. If omitted, uses the default list ('@default').",
                },
                "show_completed": {
                    "type": "boolean",
                    "description": "Include completed tasks (default false)",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max tasks to return (default 20, max 100)",
                },
            },
        },
    },
    {
        "name": "google_get_task",
        "description": "Get full details of a specific Google task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_list_id": {
                    "type": "string",
                    "description": "Task list ID. Default: '@default'.",
                },
                "task_id": {
                    "type": "string",
                    "description": "The task ID to look up",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "google_create_task",
        "description": "Create a new task in Google Tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_list_id": {
                    "type": "string",
                    "description": "Task list ID. Default: '@default'.",
                },
                "title": {
                    "type": "string",
                    "description": "Task title",
                },
                "notes": {
                    "type": "string",
                    "description": "Optional notes / details",
                },
                "due_date": {
                    "type": "string",
                    "description": "Optional due date in ISO 8601 format, e.g. '2025-03-15' or '2025-03-15T10:00:00'",
                },
            },
            "required": ["title"],
        },
    },
    {
        "name": "google_complete_task",
        "description": "Mark a Google task as completed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_list_id": {
                    "type": "string",
                    "description": "Task list ID. Default: '@default'.",
                },
                "task_id": {
                    "type": "string",
                    "description": "The task ID to complete",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "google_delete_task",
        "description": "Delete a task from Google Tasks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "task_list_id": {
                    "type": "string",
                    "description": "Task list ID. Default: '@default'.",
                },
                "task_id": {
                    "type": "string",
                    "description": "The task ID to delete",
                },
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "google_create_task_list",
        "description": "Create a new Google Tasks list.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Name for the new task list",
                },
            },
            "required": ["title"],
        },
    },
]


def _get_tasks_service():
    """Get authenticated Google Tasks API service."""
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
            "Google Tasks not authenticated. Run 'python auth_gmail.py' to set up authentication (includes Tasks scope)."
        )

    return build("tasks", "v1", credentials=creds)


def _format_task(task):
    """Format a Google Tasks task into a clean dict."""
    tz = ZoneInfo(USER_TIMEZONE)
    result = {
        "id": task.get("id", ""),
        "title": task.get("title", "(no title)"),
        "status": task.get("status", ""),
        "completed": task.get("status") == "completed",
    }

    if task.get("notes"):
        result["notes"] = task["notes"][:500]

    if task.get("due"):
        try:
            due_dt = datetime.fromisoformat(task["due"].replace("Z", "+00:00"))
            result["due"] = due_dt.astimezone(tz).strftime("%Y-%m-%d")
        except Exception:
            result["due"] = task["due"]

    if task.get("completed"):
        try:
            comp_dt = datetime.fromisoformat(task["completed"].replace("Z", "+00:00"))
            result["completed_date"] = comp_dt.astimezone(tz).isoformat()
        except Exception:
            result["completed_date"] = task["completed"]

    if task.get("parent"):
        result["parent_id"] = task["parent"]

    return result


async def execute_google_task_tool(name: str, input_data: dict, chat_id: int) -> str:
    try:
        service = _get_tasks_service()
    except RuntimeError as e:
        return json.dumps({"error": str(e)})

    if name == "google_list_task_lists":
        try:
            result = service.tasklists().list(maxResults=100).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to list task lists: {str(e)}"})

        lists = []
        for tl in result.get("items", []):
            lists.append({
                "id": tl.get("id", ""),
                "title": tl.get("title", ""),
            })
        return json.dumps({"task_lists": lists})

    elif name == "google_list_tasks":
        task_list_id = input_data.get("task_list_id", "@default")
        show_completed = input_data.get("show_completed", False)
        max_results = min(input_data.get("max_results", 20), 100)

        try:
            result = service.tasks().list(
                tasklist=task_list_id,
                maxResults=max_results,
                showCompleted=show_completed,
                showHidden=show_completed,
            ).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to list tasks: {str(e)}"})

        tasks = []
        for task in result.get("items", []):
            if task.get("title"):  # skip empty tasks
                tasks.append(_format_task(task))

        return json.dumps({"tasks": tasks, "count": len(tasks), "task_list_id": task_list_id})

    elif name == "google_get_task":
        task_list_id = input_data.get("task_list_id", "@default")
        task_id = input_data["task_id"]

        try:
            task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
        except Exception as e:
            return json.dumps({"error": f"Task not found: {str(e)}"})

        return json.dumps(_format_task(task))

    elif name == "google_create_task":
        task_list_id = input_data.get("task_list_id", "@default")
        body = {"title": input_data["title"]}

        if input_data.get("notes"):
            body["notes"] = input_data["notes"]

        if input_data.get("due_date"):
            due_str = input_data["due_date"]
            tz = ZoneInfo(USER_TIMEZONE)
            try:
                if "T" in due_str:
                    dt = datetime.fromisoformat(due_str)
                else:
                    dt = datetime.strptime(due_str, "%Y-%m-%d")
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=tz)
                # Google Tasks API wants RFC 3339 format
                body["due"] = dt.isoformat()
            except Exception:
                body["due"] = due_str + "T00:00:00.000Z"

        try:
            task = service.tasks().insert(tasklist=task_list_id, body=body).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to create task: {str(e)}"})

        return json.dumps({
            "status": "created",
            "id": task.get("id", ""),
            "title": task.get("title", ""),
            "task_list_id": task_list_id,
        })

    elif name == "google_complete_task":
        task_list_id = input_data.get("task_list_id", "@default")
        task_id = input_data["task_id"]

        try:
            task = service.tasks().get(tasklist=task_list_id, task=task_id).execute()
            task["status"] = "completed"
            updated = service.tasks().update(
                tasklist=task_list_id, task=task_id, body=task
            ).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to complete task: {str(e)}"})

        return json.dumps({"status": "completed", "id": task_id, "title": updated.get("title", "")})

    elif name == "google_delete_task":
        task_list_id = input_data.get("task_list_id", "@default")
        task_id = input_data["task_id"]

        try:
            service.tasks().delete(tasklist=task_list_id, task=task_id).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to delete task: {str(e)}"})

        return json.dumps({"status": "deleted", "task_id": task_id})

    elif name == "google_create_task_list":
        title = input_data["title"]

        try:
            tl = service.tasklists().insert(body={"title": title}).execute()
        except Exception as e:
            return json.dumps({"error": f"Failed to create task list: {str(e)}"})

        return json.dumps({
            "status": "created",
            "id": tl.get("id", ""),
            "title": tl.get("title", ""),
        })

    return json.dumps({"error": f"Unknown task tool: {name}"})
