---
name: system
description: System utilities, time, shell commands
tools: [get_current_time, run_command, get_usage, set_credit_balance, log_bot_error]
---
- Tell the current date and time
- Run shell commands on the local machine
- Check API usage and costs
- Log your own mistakes: when the user says "log this", "add to error log", "תוסיף לerror log" or similar, call `log_bot_error` with an honest description. Never reply "נרשם"/"logged" without actually calling the tool.
