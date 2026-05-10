import json
from memory import store_memory, recall_memories, get_all_memories, delete_memory

MEMORY_TOOLS = [
    {
        "name": "remember",
        "description": "Store a fact or piece of information to long-term memory. Use this proactively when the user shares personal info, preferences, or important details.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Short label for this memory (e.g. 'name', 'favorite_food', 'work_project')"
                },
                "value": {
                    "type": "string",
                    "description": "The information to store"
                },
            },
            "required": ["key", "value"],
        },
    },
    {
        "name": "recall",
        "description": "Search long-term memory for previously stored facts. Use when you need context about the user or past information.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term to look for in stored memories"
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_memories",
        "description": "List all stored memories for the current user.",
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "forget",
        "description": "Delete a specific memory by its key.",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "The key of the memory to delete"
                },
            },
            "required": ["key"],
        },
    },
]


async def execute_memory_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name == "remember":
        await store_memory(chat_id, input_data["key"], input_data["value"])
        return json.dumps({"status": "remembered", "key": input_data["key"]})

    elif name == "recall":
        results = await recall_memories(chat_id, input_data["query"])
        return json.dumps({"results": results})

    elif name == "list_memories":
        memories = await get_all_memories(chat_id)
        return json.dumps({"memories": memories})

    elif name == "forget":
        await delete_memory(chat_id, input_data["key"])
        return json.dumps({"status": "forgotten", "key": input_data["key"]})

    return json.dumps({"error": f"Unknown memory tool: {name}"})
