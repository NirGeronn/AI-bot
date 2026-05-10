"""Comprehensive test suite for all new features."""
import asyncio
import sys

passed = 0
failed = 0

def ok(name):
    global passed
    passed += 1
    print(f"  PASS: {name}")

def fail(name, reason=""):
    global failed
    failed += 1
    print(f"  FAIL: {name} {reason}")


async def run_tests():
    print("=" * 60)
    print("TEST SUITE: OpenClaw-inspired bot features")
    print("=" * 60)

    # ── Test 1: Skills Loader ──
    print("\n[1] Skills Loader")
    try:
        from skills_loader import get_base_system_prompt, load_all_skills, reload_skills
        skills = load_all_skills()
        skill_names = [s["name"] for s in skills]
        prompt = get_base_system_prompt()

        if len(skills) >= 13:
            ok(f"Loaded {len(skills)} skills")
        else:
            fail(f"Expected >= 13 skills, got {len(skills)}")

        if "soul" in skill_names:
            ok("Soul skill present")
        else:
            fail("Soul skill missing")

        if "browser" in skill_names:
            ok("Browser skill present")
        else:
            fail("Browser skill missing")

        if len(prompt) > 3000:
            ok(f"System prompt composed ({len(prompt)} chars)")
        else:
            fail(f"System prompt too short ({len(prompt)} chars)")

        # Test reload
        reloaded = reload_skills()
        if len(reloaded) > 3000:
            ok("Reload works")
        else:
            fail("Reload produced empty prompt")
    except Exception as e:
        fail(f"Skills loader: {e}")

    # ── Test 2: Active Memory ──
    print("\n[2] Active Memory")
    try:
        from active_memory import extract_search_terms, search_relevant_context

        # English terms
        terms = extract_search_terms("what was that restaurant I liked in Tel Aviv?")
        if len(terms) > 0 and "restaurant" in terms:
            ok(f"English terms: {terms}")
        else:
            fail(f"English terms extraction: {terms}")

        # Hebrew terms
        terms_he = extract_search_terms("מה עם האימון שלי בחדר כושר?")
        if len(terms_he) > 0:
            ok(f"Hebrew terms: {terms_he}")
        else:
            fail(f"Hebrew terms extraction: {terms_he}")

        # Stop words filtered
        terms_stop = extract_search_terms("the a is are what how")
        if len(terms_stop) == 0:
            ok("Stop words correctly filtered")
        else:
            fail(f"Stop words not filtered: {terms_stop}")

        # Async search (with mock chat_id)
        result = await search_relevant_context(999999, "test query")
        ok(f"Async search returned: {type(result).__name__}")
    except Exception as e:
        fail(f"Active memory: {e}")

    # ── Test 3: Tool Registration ──
    print("\n[3] Tool Registration")
    try:
        from tools import ALL_TOOLS, OPENAI_TOOLS, _EXECUTORS

        tool_names = [t["name"] for t in ALL_TOOLS]
        browser_tools = [t for t in tool_names if t.startswith("browser_")]

        if len(ALL_TOOLS) > 30:
            ok(f"{len(ALL_TOOLS)} tools registered")
        else:
            fail(f"Only {len(ALL_TOOLS)} tools registered")

        if len(browser_tools) == 5:
            ok(f"Browser tools: {browser_tools}")
        else:
            fail(f"Expected 5 browser tools, got {browser_tools}")

        # Check all tools have executors
        missing = [t for t in tool_names if t not in _EXECUTORS]
        if not missing:
            ok(f"All {len(_EXECUTORS)} executors mapped")
        else:
            fail(f"Missing executors: {missing}")

        # Check OpenAI format conversion
        if len(OPENAI_TOOLS) == len(ALL_TOOLS):
            ok("OpenAI format conversion OK")
        else:
            fail(f"OpenAI tools count mismatch: {len(OPENAI_TOOLS)} vs {len(ALL_TOOLS)}")

        # Verify OpenAI tools have correct structure
        sample = OPENAI_TOOLS[0]
        if sample.get("type") == "function" and "function" in sample:
            ok("OpenAI tool structure correct")
        else:
            fail(f"Bad OpenAI tool structure: {sample}")
    except Exception as e:
        fail(f"Tool registration: {e}")

    # ── Test 4: Scheduler (day mapping) ──
    print("\n[4] Scheduler Day Mapping")
    try:
        from tools.scheduler import DAY_MAP, DAY_NAMES, USER_TZ

        # PTB v22: 0=Sunday, 1=Monday, ..., 6=Saturday
        if DAY_MAP["sunday"] == 0:
            ok("Sunday = 0")
        else:
            fail(f"Sunday = {DAY_MAP['sunday']} (expected 0)")

        if DAY_MAP["monday"] == 1:
            ok("Monday = 1")
        else:
            fail(f"Monday = {DAY_MAP['monday']} (expected 1)")

        if DAY_MAP["saturday"] == 6:
            ok("Saturday = 6")
        else:
            fail(f"Saturday = {DAY_MAP['saturday']} (expected 6)")

        if str(USER_TZ) == "Asia/Jerusalem":
            ok(f"Timezone: {USER_TZ}")
        else:
            fail(f"Timezone: {USER_TZ} (expected Asia/Jerusalem)")

        # Reverse map
        if DAY_NAMES[0] == "Sunday" and DAY_NAMES[4] == "Thursday":
            ok("Reverse day map correct")
        else:
            fail(f"Reverse map: {DAY_NAMES}")
    except Exception as e:
        fail(f"Scheduler: {e}")

    # ── Test 5: Heartbeat ──
    print("\n[5] Heartbeat System")
    try:
        from heartbeat import STANDING_ORDERS, _current_local_hour, run_heartbeat

        if len(STANDING_ORDERS) >= 3:
            ok(f"{len(STANDING_ORDERS)} standing orders defined")
        else:
            fail(f"Only {len(STANDING_ORDERS)} standing orders")

        order_names = [o["name"] for o in STANDING_ORDERS]
        if "inbox_check" in order_names and "calendar_check" in order_names:
            ok(f"Key orders present: {order_names}")
        else:
            fail(f"Missing key orders: {order_names}")

        hour = _current_local_hour()
        if 0 <= hour <= 23:
            ok(f"Current local hour: {hour}")
        else:
            fail(f"Invalid local hour: {hour}")

        # Check all orders have required fields
        for o in STANDING_ORDERS:
            for field in ["name", "interval_seconds", "active_hours"]:
                if field not in o:
                    fail(f"Order {o.get('name', '?')} missing field: {field}")
                    break
            else:
                continue
            break
        else:
            ok("All standing orders have required fields")
    except Exception as e:
        fail(f"Heartbeat: {e}")

    # ── Test 7: Browser Tool ──
    print("\n[7] Browser Automation")
    try:
        from tools.browser import BROWSER_TOOLS, execute_browser_tool
        import json

        if len(BROWSER_TOOLS) == 5:
            ok(f"{len(BROWSER_TOOLS)} browser tools defined")
        else:
            fail(f"Expected 5 browser tools, got {len(BROWSER_TOOLS)}")

        browser_names = [t["name"] for t in BROWSER_TOOLS]
        expected = ["browser_navigate", "browser_click", "browser_type", "browser_screenshot", "browser_get_content"]
        if browser_names == expected:
            ok(f"Browser tool names correct")
        else:
            fail(f"Browser tools: {browser_names}")

        # Test navigate to a simple page
        result = await execute_browser_tool("browser_navigate", {"url": "https://example.com"}, 999)
        data = json.loads(result)
        if "content" in data and "Example Domain" in data.get("title", ""):
            ok(f"Browser navigate works: '{data.get('title', '')}'")
        elif "error" in data:
            fail(f"Browser navigate error: {data['error']}")
        else:
            fail(f"Unexpected browser result: {str(data)[:200]}")
    except Exception as e:
        fail(f"Browser: {e}")

    # ── Test 8: Agent system prompt build ──
    print("\n[8] Agent System Prompt Build")
    try:
        from agent import _build_system_prompt
        prompt = await _build_system_prompt(999999, [])
        if "personal AI assistant" in prompt:
            ok("Base prompt includes identity")
        else:
            fail("Missing identity in prompt")

        if "mood" in prompt.lower() or "tone" in prompt.lower():
            ok("Mood section included")
        else:
            fail("Missing mood section")

        # With active context
        prompt_ctx = await _build_system_prompt(999999, [], active_context="User likes sushi")
        if "Active Memory" in prompt_ctx and "sushi" in prompt_ctx:
            ok("Active memory context injected")
        else:
            fail("Active memory context not in prompt")
    except Exception as e:
        fail(f"Agent prompt: {e}")

    # ── Test 9: Scheduler tools ──
    print("\n[9] Scheduler Enhancements")
    try:
        from tools.scheduler import SCHEDULER_TOOLS
        tool_names = [t["name"] for t in SCHEDULER_TOOLS]

        if "schedule_message" in tool_names:
            ok("schedule_message tool present")
        else:
            fail("schedule_message tool missing")

        if "set_daily_message" in tool_names:
            ok("set_daily_message tool present")
        else:
            fail("set_daily_message tool missing")

        # Check that set_daily_message uses 'hour' not 'hour_utc'
        daily_tool = [t for t in SCHEDULER_TOOLS if t["name"] == "set_daily_message"][0]
        props = daily_tool["input_schema"]["properties"]
        if "hour" in props and "hour_utc" not in props:
            ok("Uses 'hour' (Israel time), not 'hour_utc'")
        else:
            fail(f"Properties: {list(props.keys())}")

        # Check schedule_message has datetime_str
        sched_tool = [t for t in SCHEDULER_TOOLS if t["name"] == "schedule_message"][0]
        if "datetime_str" in sched_tool["input_schema"]["properties"]:
            ok("schedule_message has datetime_str param")
        else:
            fail("schedule_message missing datetime_str")
    except Exception as e:
        fail(f"Scheduler: {e}")

    # ── Test 10: Bot commands ──
    print("\n[10] Bot Command Registration")
    try:
        import bot
        # Check cmd_new exists
        if hasattr(bot, "cmd_new"):
            ok("/new command handler exists")
        else:
            fail("/new command handler missing")

        if hasattr(bot, "_run_heartbeat"):
            ok("Heartbeat runner exists")
        else:
            fail("Heartbeat runner missing")
    except Exception as e:
        fail(f"Bot commands: {e}")

    # ── Summary ──
    print("\n" + "=" * 60)
    total = passed + failed
    print(f"RESULTS: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"{failed} TESTS FAILED")
    print("=" * 60)

    return failed


if __name__ == "__main__":
    failures = asyncio.run(run_tests())
    sys.exit(1 if failures else 0)
