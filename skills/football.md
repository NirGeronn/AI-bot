---
name: football
description: Football (soccer) games, scores, and fixtures
tools: [get_football_games]
---
You can fetch football (soccer) games for any date — fixtures, kickoff times, live scores, and final results — via 365scores.

*CRITICAL*: For ANY question about football fixtures, kickoff times, or scores ("איזה משחקים היום?", "מה המשחקים הערב?", "what games are on?", etc.), you MUST call get_football_games. NEVER answer from memory — fixtures change daily and getting them wrong is worse than not answering. If the tool fails, say it failed; do not guess.

*Usage*:
- Default returns today's games in {timezone}.
- Use `top_only: true` for the major leagues (Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Liga Portugal, Champions/Europa/Conference League, Israeli Premier League). Default to top_only=true unless the user asks for lower divisions.
- Filter by `competition` (substring, e.g. "Premier League", "ליגת העל") or `country` ("Israel", "England").
- For a daily football briefing, combine with set_daily_message — when the scheduled message fires, call get_football_games and summarize naturally for {owner_name}.

*Output handling*: present games grouped by competition. Show kickoff time, both teams, and the score (or "טרם החל" / "Scheduled" if not started). Highlight live games. Keep it tight — don't dump every youth/reserve match unless asked. If the tool returns zero games, say so plainly — DO NOT invent fixtures.
