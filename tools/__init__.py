from tools.memory_tools import MEMORY_TOOLS, execute_memory_tool
from tools.system import SYSTEM_TOOLS, execute_system_tool
from tools.web import WEB_TOOLS, execute_web_tool
from tools.gmail import GMAIL_TOOLS, execute_gmail_tool
from tools.scheduler import SCHEDULER_TOOLS, execute_scheduler_tool
from config import CALENDAR_PROVIDER
from tools.google_tasks import GOOGLE_TASK_TOOLS, execute_google_task_tool
if CALENDAR_PROVIDER == "icloud":
    from tools.icloud_calendar import CALENDAR_TOOLS, execute_calendar_tool
    from tools.icloud_contacts import ICLOUD_CONTACT_TOOLS, execute_icloud_contact_tool
    GOOGLE_CONTACT_TOOLS = []
else:
    from tools.calendar import CALENDAR_TOOLS, execute_calendar_tool
    from tools.google_contacts import GOOGLE_CONTACT_TOOLS, execute_google_contact_tool
    ICLOUD_CONTACT_TOOLS = []
from tools.weather import WEATHER_TOOLS, execute_weather_tool
from tools.todo import TODO_TOOLS, execute_todo_tool
from tools.utilities import UTILITY_TOOLS, execute_utility_tool
from tools.trends import TRENDS_TOOLS, execute_trends_tool
from tools.browser import BROWSER_TOOLS, execute_browser_tool
from tools.anthropic_billing import ANTHROPIC_BILLING_TOOLS, execute_anthropic_billing_tool
from tools.football import FOOTBALL_TOOLS, execute_football_tool

# Unified alias for contacts (used by tool_router)
CONTACT_TOOLS = ICLOUD_CONTACT_TOOLS if CALENDAR_PROVIDER == "icloud" else GOOGLE_CONTACT_TOOLS

ALL_TOOLS = (
    MEMORY_TOOLS + SYSTEM_TOOLS + WEB_TOOLS + GMAIL_TOOLS +
    SCHEDULER_TOOLS + CALENDAR_TOOLS +
    ICLOUD_CONTACT_TOOLS + GOOGLE_CONTACT_TOOLS +
    GOOGLE_TASK_TOOLS +
    WEATHER_TOOLS +
    TODO_TOOLS + UTILITY_TOOLS + TRENDS_TOOLS +
    BROWSER_TOOLS + ANTHROPIC_BILLING_TOOLS + FOOTBALL_TOOLS
)


_EXECUTORS = {}
for tool in MEMORY_TOOLS:
    _EXECUTORS[tool["name"]] = execute_memory_tool
for tool in SYSTEM_TOOLS:
    _EXECUTORS[tool["name"]] = execute_system_tool
for tool in WEB_TOOLS:
    _EXECUTORS[tool["name"]] = execute_web_tool
for tool in GMAIL_TOOLS:
    _EXECUTORS[tool["name"]] = execute_gmail_tool
for tool in SCHEDULER_TOOLS:
    _EXECUTORS[tool["name"]] = execute_scheduler_tool
for tool in CALENDAR_TOOLS:
    _EXECUTORS[tool["name"]] = execute_calendar_tool
for tool in ICLOUD_CONTACT_TOOLS:
    _EXECUTORS[tool["name"]] = execute_icloud_contact_tool
for tool in GOOGLE_CONTACT_TOOLS:
    _EXECUTORS[tool["name"]] = execute_google_contact_tool
for tool in GOOGLE_TASK_TOOLS:
    _EXECUTORS[tool["name"]] = execute_google_task_tool
for tool in WEATHER_TOOLS:
    _EXECUTORS[tool["name"]] = execute_weather_tool
for tool in TODO_TOOLS:
    _EXECUTORS[tool["name"]] = execute_todo_tool
for tool in UTILITY_TOOLS:
    _EXECUTORS[tool["name"]] = execute_utility_tool
for tool in TRENDS_TOOLS:
    _EXECUTORS[tool["name"]] = execute_trends_tool
for tool in BROWSER_TOOLS:
    _EXECUTORS[tool["name"]] = execute_browser_tool
for tool in ANTHROPIC_BILLING_TOOLS:
    _EXECUTORS[tool["name"]] = execute_anthropic_billing_tool
for tool in FOOTBALL_TOOLS:
    _EXECUTORS[tool["name"]] = execute_football_tool


async def execute_tool(name: str, input_data: dict, chat_id: int) -> str:
    executor = _EXECUTORS.get(name)
    if not executor:
        return f'{{"error": "Unknown tool: {name}"}}'
    return await executor(name, input_data, chat_id)
