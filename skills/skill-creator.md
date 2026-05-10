---
name: skill-creator
description: Create new skill markdown files from a description so future-you has new capabilities
---

## Skill Creator

Use the **create_skill** tool when the user says something like "teach yourself how to X", "add a skill for Y", or "remember from now on you can do Z" — and Z is a coherent capability that warrants its own skill file rather than a one-off memory.

When to use:
- The capability is reusable (will apply across many future conversations).
- It belongs in the system prompt, not in user memory.
- Examples: "from now on, when I share a YouTube link, always offer to summarize it" → new skill.

Inputs you should provide to the tool:
- `name`: short kebab-case name (e.g., "youtube-autosummary").
- `description`: one-line description for the frontmatter.
- `body`: the markdown body — explain when to use, how to use, and any constraints. Keep it short and concrete.

After creating, tell the user the skill was added and that it'll be active on the next bot restart (skills are cached at startup; the tool will reload them in-process so you can use it immediately).
