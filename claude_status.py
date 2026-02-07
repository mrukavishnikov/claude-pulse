#!/usr/bin/env python3
"""Minimal Claude Code status line — fetches real usage data from Anthropic's OAuth API."""

import json
import os
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CACHE_TTL = 30
BAR_WIDTH = 8
FILL = "\u2501"   # ━ (thin horizontal bar)
EMPTY = "\u2500"   # ─ (thin line)

# ANSI colour codes
GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
DIM = "\033[2m"
RESET = "\033[0m"

PLAN_NAMES = {
    "default_claude_pro": "Pro",
    "default_claude_max_5x": "Max 5x",
    "default_claude_max_20x": "Max 20x",
}


def load_config():
    config_path = Path(__file__).parent / "config.json"
    try:
        with open(config_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_cache_path():
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    cache_dir = base / "claude-status"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "cache.json"


def read_cache(cache_path, ttl):
    try:
        with open(cache_path, "r") as f:
            cached = json.load(f)
        if time.time() - cached.get("timestamp", 0) < ttl:
            return cached.get("line", "")
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    return None


def write_cache(cache_path, line):
    try:
        with open(cache_path, "w") as f:
            json.dump({"timestamp": time.time(), "line": line}, f)
    except OSError:
        pass


def get_credentials():
    """Read OAuth token and plan info from Claude Code's credentials file."""
    creds_path = Path.home() / ".claude" / ".credentials.json"
    try:
        with open(creds_path, "r") as f:
            data = json.load(f)
        oauth = data.get("claudeAiOauth", {})
        token = oauth.get("accessToken")
        tier = oauth.get("rateLimitTier", "")
        if not token:
            return None, None
        plan = PLAN_NAMES.get(tier, tier.replace("default_claude_", "").replace("_", " ").title())
        return token, plan
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None, None


def fetch_usage(token):
    req = urllib.request.Request(
        "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def bar_colour(pct):
    """Return ANSI colour based on usage percentage: green < 50, yellow < 80, red >= 80."""
    if pct >= 80:
        return RED
    if pct >= 50:
        return YELLOW
    return GREEN


def make_bar(pct):
    """Build a thin coloured bar."""
    filled = round(pct / 100 * BAR_WIDTH)
    filled = max(0, min(BAR_WIDTH, filled))
    colour = bar_colour(pct)
    return f"{colour}{FILL * filled}{DIM}{EMPTY * (BAR_WIDTH - filled)}{RESET}"


def format_reset_time(resets_at_str):
    if not resets_at_str:
        return None
    try:
        resets_at = datetime.fromisoformat(resets_at_str)
        now = datetime.now(timezone.utc)
        total_seconds = int((resets_at - now).total_seconds())
        if total_seconds <= 0:
            return "now"
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        if hours > 0:
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m"
    except (ValueError, TypeError):
        return None


def build_status_line(usage, plan):
    parts = []

    # Current Session (5-hour block)
    five = usage.get("five_hour")
    if five:
        pct = five.get("utilization", 0)
        bar = make_bar(pct)
        reset = format_reset_time(five.get("resets_at"))
        reset_str = f" {reset}" if reset else ""
        parts.append(f"Session {bar} {pct:.0f}%{reset_str}")
    else:
        parts.append(f"Session {make_bar(0)} 0%")

    # Weekly Limit (7-day all models)
    seven = usage.get("seven_day")
    if seven:
        pct = seven.get("utilization", 0)
        bar = make_bar(pct)
        parts.append(f"Weekly {bar} {pct:.0f}%")

    # Plan name
    if plan:
        parts.append(plan)

    return " | ".join(parts)


def install_status_line():
    settings_path = Path.home() / ".claude" / "settings.json"
    script_path = Path(__file__).resolve()

    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, "r") as f:
                settings = json.load(f)
        except (json.JSONDecodeError, OSError):
            pass

    settings["statusLine"] = {
        "type": "command",
        "command": f'python "{script_path}"',
    }

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    print(f"Installed status line to {settings_path}")
    print(f"Command: python \"{script_path}\"")
    print("Restart Claude Code to see the status line.")


def main():
    if "--install" in sys.argv:
        install_status_line()
        return

    config = load_config()
    cache_ttl = config.get("cache_ttl_seconds", DEFAULT_CACHE_TTL)

    try:
        sys.stdin.read()
    except Exception:
        pass

    cache_path = get_cache_path()
    cached = read_cache(cache_path, cache_ttl)
    if cached is not None:
        sys.stdout.buffer.write((cached + "\n").encode("utf-8"))
        return

    token, plan = get_credentials()
    if not token:
        line = "No credentials found"
        write_cache(cache_path, line)
        sys.stdout.buffer.write((line + "\n").encode("utf-8"))
        return

    try:
        usage = fetch_usage(token)
        line = build_status_line(usage, plan)
    except urllib.error.HTTPError as e:
        line = f"API error: {e.code}"
    except Exception:
        line = "Usage unavailable"

    write_cache(cache_path, line)
    sys.stdout.buffer.write((line + "\n").encode("utf-8"))


if __name__ == "__main__":
    main()
