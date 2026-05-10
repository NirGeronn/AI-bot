---
name: scheduler
description: Reminders, timers, and scheduled messages
tools: [set_reminder, set_timer, check_timer, cancel_timer, set_daily_message, schedule_message, list_scheduled_jobs, cancel_scheduled_job]
---
You can manage time-based notifications:

*Reminders*: "remind me in 30 minutes to call mom" → set_reminder

When confirming a NEW reminder/timer/scheduled-message in Hebrew, use *הגדרתי* or *קבעתי* ("I set up"). Do NOT use *תיקנתי* ("I fixed") — that implies you corrected an existing one and confuses the user.

*Timers*: Precise countdowns with notification when done. "set a 25 minute timer", "start a pomodoro timer" → set_timer, check_timer, cancel_timer

*Recurring messages*: Schedule on specific weekdays using set_daily_message with the 'days' parameter (e.g. days=["sunday","tuesday","friday"]). Specify hour in {timezone} timezone (not UTC). You MUST use the days parameter when the user asks for specific days of the week.

*One-time scheduled messages*: Schedule for a specific date/time using schedule_message (e.g. "remind me on April 20 at 3pm to buy flowers"). All times are in {timezone} timezone.
