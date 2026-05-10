leג# Contributing

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

1. Fork and clone the repo
2. Copy `.env.example` to `.env` and fill in your keys
3. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   playwright install chromium
   ```
4. Run the bot: `python bot.py`

## Adding a New Tool

Tools live in `tools/` and follow a consistent pattern:

1. Create `tools/your_tool.py` with:
   - A `YOUR_TOOLS` list containing tool schemas (Anthropic format)
   - An `async def execute_your_tool(name, input_data, chat_id) -> str` function
2. Register your tool in `tools/__init__.py`
3. Create a matching skill file `skills/your_tool.md` with frontmatter and a description

### Tool Schema Format

Tool schemas use Anthropic's format and are auto-converted to OpenAI format at runtime:

```python
YOUR_TOOLS = [
    {
        "name": "tool_name",
        "description": "What this tool does and when to use it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "Param description"},
            },
            "required": ["param"],
        },
    },
]
```

### Skill File Format

```markdown
---
name: your_tool
description: Brief description
tools: [tool_name]
---
Instructions for the AI on when and how to use this tool.
```

Template variables available in skill files: `{owner_name}`, `{timezone}`, `{language}`, `{model}`.

## Adding a New Skill (No Code)

Skills are markdown files in `skills/` that compose the system prompt. You can add behavioral instructions, policies, or personality traits without writing any Python:

1. Create `skills/your_skill.md` with YAML frontmatter
2. Set `always: true` if it should always be included in the prompt
3. The skill body becomes part of the system prompt

## Code Style

- Async/await throughout (the bot is fully async)
- Keep tool execute functions returning JSON strings
- Use `logging` instead of `print`
- Keep responses concise - this runs on Telegram

## Pull Requests

- Keep PRs focused on a single change
- Test with your own bot instance before submitting
- Update skill files if you change tool behavior
