import json
import time
import aiosqlite
from config import DB_PATH

TODO_TOOLS = [
    {
        "name": "todo_add",
        "description": "Add one or more items to a todo list. Creates the list if it doesn't exist. Use this when the user wants to add tasks, items, or things to do. Examples: 'add buy milk to my shopping list', 'add these tasks to my work list: review PR, fix bug, deploy'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {
                    "type": "string",
                    "description": "Name of the todo list (e.g. 'shopping', 'work', 'personal'). Defaults to 'default'.",
                },
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of todo items to add",
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "todo_list",
        "description": "Show all items in a todo list (or all lists if no name given). Use this when the user asks to see their tasks, todos, or lists.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {
                    "type": "string",
                    "description": "Name of the list to show. If omitted, shows all lists.",
                },
                "show_completed": {
                    "type": "boolean",
                    "description": "Whether to include completed items. Default false.",
                },
            },
        },
    },
    {
        "name": "todo_complete",
        "description": "Mark one or more todo items as completed. Match items by their text (partial match is fine). Use when the user says they finished, completed, or done with a task.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {
                    "type": "string",
                    "description": "Name of the list. Defaults to 'default'.",
                },
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Text of items to mark as complete (partial match supported)",
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "todo_remove",
        "description": "Remove/delete one or more items from a todo list entirely. Use when the user wants to remove items (not just complete them).",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {
                    "type": "string",
                    "description": "Name of the list. Defaults to 'default'.",
                },
                "items": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Text of items to remove (partial match supported)",
                },
            },
            "required": ["items"],
        },
    },
    {
        "name": "todo_delete_list",
        "description": "Delete an entire todo list and all its items.",
        "input_schema": {
            "type": "object",
            "properties": {
                "list_name": {
                    "type": "string",
                    "description": "Name of the list to delete",
                },
            },
            "required": ["list_name"],
        },
    },
]


async def _ensure_table():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS todo_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                list_name TEXT NOT NULL DEFAULT 'default',
                item TEXT NOT NULL,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                completed_at REAL
            );
            CREATE INDEX IF NOT EXISTS idx_todo_chat_list ON todo_items(chat_id, list_name);
        """)
        await db.commit()


async def execute_todo_tool(name: str, input_data: dict, chat_id: int) -> str:
    await _ensure_table()

    if name == "todo_add":
        list_name = input_data.get("list_name", "default").strip().lower()
        items = input_data["items"]
        now = time.time()

        async with aiosqlite.connect(DB_PATH) as db:
            for item in items:
                await db.execute(
                    "INSERT INTO todo_items (chat_id, list_name, item, created_at) VALUES (?, ?, ?, ?)",
                    (chat_id, list_name, item.strip(), now),
                )
            await db.commit()

        return json.dumps({
            "status": "added",
            "list": list_name,
            "items_added": len(items),
            "items": items,
        })

    elif name == "todo_list":
        list_name = input_data.get("list_name")
        show_completed = input_data.get("show_completed", False)

        async with aiosqlite.connect(DB_PATH) as db:
            if list_name:
                list_name = list_name.strip().lower()
                if show_completed:
                    cursor = await db.execute(
                        "SELECT item, completed FROM todo_items WHERE chat_id = ? AND list_name = ? ORDER BY completed ASC, created_at ASC",
                        (chat_id, list_name),
                    )
                else:
                    cursor = await db.execute(
                        "SELECT item, completed FROM todo_items WHERE chat_id = ? AND list_name = ? AND completed = 0 ORDER BY created_at ASC",
                        (chat_id, list_name),
                    )
                rows = await cursor.fetchall()
                items = [{"item": r[0], "completed": bool(r[1])} for r in rows]
                return json.dumps({"list": list_name, "items": items, "count": len(items)})
            else:
                # Show all lists
                cursor = await db.execute(
                    "SELECT DISTINCT list_name FROM todo_items WHERE chat_id = ? AND completed = 0",
                    (chat_id,),
                )
                list_names = [r[0] for r in await cursor.fetchall()]

                all_lists = {}
                for ln in list_names:
                    cursor = await db.execute(
                        "SELECT item, completed FROM todo_items WHERE chat_id = ? AND list_name = ? AND completed = 0 ORDER BY created_at ASC",
                        (chat_id, ln),
                    )
                    rows = await cursor.fetchall()
                    all_lists[ln] = [{"item": r[0], "completed": bool(r[1])} for r in rows]

                return json.dumps({"lists": all_lists, "total_lists": len(all_lists)})

    elif name == "todo_complete":
        list_name = input_data.get("list_name", "default").strip().lower()
        items = input_data["items"]
        now = time.time()
        completed = []

        async with aiosqlite.connect(DB_PATH) as db:
            for search in items:
                # First try the specified list
                cursor = await db.execute(
                    "SELECT id, item, list_name FROM todo_items WHERE chat_id = ? AND list_name = ? AND completed = 0 AND item LIKE ?",
                    (chat_id, list_name, f"%{search.strip()}%"),
                )
                rows = await cursor.fetchall()

                # If not found in specified list, search all lists
                if not rows:
                    cursor = await db.execute(
                        "SELECT id, item, list_name FROM todo_items WHERE chat_id = ? AND completed = 0 AND item LIKE ?",
                        (chat_id, f"%{search.strip()}%"),
                    )
                    rows = await cursor.fetchall()

                for row_id, item_text, found_list in rows:
                    await db.execute(
                        "UPDATE todo_items SET completed = 1, completed_at = ? WHERE id = ?",
                        (now, row_id),
                    )
                    completed.append(f"{item_text} (from {found_list})")
            await db.commit()

        if not completed:
            return json.dumps({"status": "no_match", "message": f"No pending items matching {items} were found in any list."})

        return json.dumps({"status": "completed", "completed_items": completed})

    elif name == "todo_remove":
        list_name = input_data.get("list_name", "default").strip().lower()
        items = input_data["items"]
        removed = []

        async with aiosqlite.connect(DB_PATH) as db:
            for search in items:
                cursor = await db.execute(
                    "SELECT id, item, list_name FROM todo_items WHERE chat_id = ? AND list_name = ? AND item LIKE ?",
                    (chat_id, list_name, f"%{search.strip()}%"),
                )
                rows = await cursor.fetchall()

                # If not found in specified list, search all lists
                if not rows:
                    cursor = await db.execute(
                        "SELECT id, item, list_name FROM todo_items WHERE chat_id = ? AND item LIKE ?",
                        (chat_id, f"%{search.strip()}%"),
                    )
                    rows = await cursor.fetchall()

                for row_id, item_text, found_list in rows:
                    await db.execute("DELETE FROM todo_items WHERE id = ?", (row_id,))
                    removed.append(f"{item_text} (from {found_list})")
            await db.commit()

        if not removed:
            return json.dumps({"status": "no_match", "message": f"No items matching {items} were found in any list."})

        return json.dumps({"status": "removed", "removed_items": removed})

    elif name == "todo_delete_list":
        list_name = input_data["list_name"].strip().lower()

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT COUNT(*) FROM todo_items WHERE chat_id = ? AND list_name = ?",
                (chat_id, list_name),
            )
            count = (await cursor.fetchone())[0]
            await db.execute(
                "DELETE FROM todo_items WHERE chat_id = ? AND list_name = ?",
                (chat_id, list_name),
            )
            await db.commit()

        return json.dumps({"status": "deleted", "list": list_name, "items_deleted": count})

    return json.dumps({"error": f"Unknown todo tool: {name}"})
