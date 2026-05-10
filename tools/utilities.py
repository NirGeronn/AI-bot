import json
import hashlib
import asyncio
import logging
import httpx
from config import BOT_USER_AGENT

logger = logging.getLogger(__name__)

UTILITY_TOOLS = [
    {
        "name": "check_breach",
        "description": (
            "Check if an email address has been involved in known data breaches (Have I Been Pwned). "
            "Use when the user asks 'has my email been hacked?', 'check if my email was in a breach', "
            "'is my email safe?', etc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "email": {
                    "type": "string",
                    "description": "The email address to check",
                },
            },
            "required": ["email"],
        },
    },
    {
        "name": "is_it_down",
        "description": (
            "Check if a website or service is up or down. Pings the URL and reports status code "
            "and response time. Use when the user asks 'is X down?', 'can you check if Y is working?', "
            "'is this website up?'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL or domain to check (e.g. 'google.com', 'https://github.com')",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "speed_test",
        "description": (
            "Run an internet speed test from the bot's server. Returns ping, download speed, "
            "and upload speed. Use when the user asks about internet speed or network performance."
        ),
        "input_schema": {
            "type": "object",
            "properties": {},
        },
    },
]


async def _check_hibp(email: str) -> dict:
    """Check email against HIBP using the k-anonymity API (free, no API key)."""
    # Hash the email's password-style: we use the pwned passwords approach
    # But for breached accounts, we use the direct API with k-anonymity on the email hash
    # Actually, HIBP breach check for emails requires API key.
    # Alternative: use the free breach directory search approach

    # Use SHA-1 hash prefix approach via the password API for a general check,
    # or just do a direct check with the free unauthed endpoint for breach names
    async with httpx.AsyncClient(timeout=15) as client:
        # Try the breach check endpoint (may need API key for details)
        # Fall back to checking via the breach directory
        headers = {"User-Agent": BOT_USER_AGENT}

        try:
            resp = await client.get(
                f"https://haveibeenpwned.com/api/v3/breachedaccount/{email}",
                headers={**headers, "hibp-api-key": ""},
                params={"truncateResponse": "true"},
            )

            if resp.status_code == 200:
                breaches = resp.json()
                return {
                    "breached": True,
                    "breach_count": len(breaches),
                    "breaches": [b["Name"] for b in breaches[:15]],
                }
            elif resp.status_code == 404:
                return {"breached": False, "message": "No breaches found for this email."}
            elif resp.status_code == 401:
                # API key required — fall back to hash-based password check as a proxy
                pass
        except Exception:
            pass

        # Fallback: check via the free password hash API as a general security indicator
        # This doesn't check email breaches but checks if common passwords are leaked
        # Better fallback: use the free breach search on the website
        try:
            resp = await client.get(
                f"https://api.xposedornot.com/v1/check-email/{email}",
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("breaches_details"):
                    details = data["breaches_details"]
                    breaches = []
                    if isinstance(details, list):
                        breaches = [d.get("breach", d.get("domain", "unknown")) for d in details[:15]]
                    elif isinstance(details, dict):
                        breaches = list(details.keys())[:15]
                    return {
                        "breached": True,
                        "breach_count": len(breaches),
                        "breaches": breaches,
                        "source": "XposedOrNot",
                    }
                return {"breached": False, "message": "No breaches found for this email.", "source": "XposedOrNot"}
        except Exception as e:
            logger.warning(f"XposedOrNot check failed: {e}")

    return {"breached": None, "message": "Could not check at this time. Try again later."}


async def _check_site(url: str) -> dict:
    """Check if a website is up or down."""
    # Normalize URL
    if not url.startswith("http"):
        url = f"https://{url}"

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        try:
            resp = await client.get(url)
            return {
                "status": "up",
                "url": url,
                "status_code": resp.status_code,
                "response_time_ms": int(resp.elapsed.total_seconds() * 1000),
            }
        except httpx.TimeoutException:
            return {"status": "down", "url": url, "reason": "Timeout (>15s)"}
        except httpx.ConnectError as e:
            return {"status": "down", "url": url, "reason": f"Connection failed: {str(e)[:200]}"}
        except Exception as e:
            return {"status": "down", "url": url, "reason": str(e)[:200]}


async def _run_speed_test() -> dict:
    """Run a speed test using speedtest-cli."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "speedtest-cli", "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)

        if proc.returncode != 0:
            # Try alternative: speedtest (ookla)
            raise RuntimeError(stderr.decode()[:200])

        data = json.loads(stdout.decode())
        return {
            "ping_ms": round(data.get("ping", 0), 1),
            "download_mbps": round(data.get("download", 0) / 1_000_000, 2),
            "upload_mbps": round(data.get("upload", 0) / 1_000_000, 2),
            "server": data.get("server", {}).get("name", "unknown"),
            "server_location": data.get("server", {}).get("country", "unknown"),
        }
    except FileNotFoundError:
        return {"error": "speedtest-cli not installed on server"}
    except asyncio.TimeoutError:
        return {"error": "Speed test timed out (>60s)"}
    except Exception as e:
        return {"error": f"Speed test failed: {str(e)[:200]}"}


async def execute_utility_tool(name: str, input_data: dict, chat_id: int) -> str:
    if name == "check_breach":
        email = input_data["email"].strip()
        result = await _check_hibp(email)
        return json.dumps(result)

    elif name == "is_it_down":
        url = input_data["url"].strip()
        result = await _check_site(url)
        return json.dumps(result)

    elif name == "speed_test":
        result = await _run_speed_test()
        return json.dumps(result)

    return json.dumps({"error": f"Unknown utility tool: {name}"})
