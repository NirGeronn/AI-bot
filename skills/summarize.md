---
name: summarize
description: Summarize long text, articles, transcripts, threads, or documents
---

## Summarize

You can produce structured summaries via the **summarize_text** tool when the user gives you a long block of text, a long article, a long Slack/email thread, or a transcript and asks for a summary, TL;DR, or "key points".

When to use:
- User says "summarize this", "tldr", "what's the key takeaway", "give me the gist".
- The input is more than ~500 words OR more than ~10 messages.
- After `browse_url`/`web_research` returns a long page and the user wants the gist (you can summarize directly without the tool — only use the tool for very long inputs >5K chars).

Output style:
- 3–7 bullets max for short summaries.
- "Headline + bullets + bottom line" for longer pieces.
- Match the user's language (Hebrew if they wrote Hebrew).
- Never invent details that aren't in the source.
