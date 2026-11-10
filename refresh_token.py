#!/usr/bin/env python3
"""Refresh the long-lived Instagram token and write it back to .env.

Long-lived tokens last 60 days and can be refreshed once they are at least 24 hours old.
launchd runs this daily with --if-due, so the refresh happens every 45 days even if the
Mac was asleep or rebooted on the exact day.

    python3 refresh_token.py --dry-run   # show status, change nothing
    python3 refresh_token.py             # refresh now
    python3 refresh_token.py --if-due    # refresh only if >= 45 days since last refresh
"""
import argparse
import datetime
import json
import os
import sys

from igcommon import HERE, GraphError, graph, load_env, redact, set_env_value

STATE_PATH = os.path.join(HERE, ".token_state.json")
REFRESH_EVERY_DAYS = 45


def now():
    return datetime.datetime.now().astimezone()


def load_state():
    if os.path.exists(STATE_PATH):
        with open(STATE_PATH) as f:
            return json.load(f)
    return {}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="report status without refreshing")
    ap.add_argument("--if-due", action="store_true",
                    help=f"only refresh if {REFRESH_EVERY_DAYS}+ days since the last refresh")
    args = ap.parse_args()

    token = load_env().get("IG_ACCESS_TOKEN")
    if not token:
        sys.exit("IG_ACCESS_TOKEN must be set in .env")

    state = load_state()
    last = state.get("refreshed_at")
    age_days = (now() - datetime.datetime.fromisoformat(last)).days if last else None
    due = age_days is None or age_days >= REFRESH_EVERY_DAYS
    print(f"[{now().isoformat(timespec='seconds')}] last refresh: "
          f"{last or 'never (by this script)'}"
          + (f" ({age_days} days ago)" if age_days is not None else "")
          + (f", expires {state['expires_at']}" if state.get("expires_at") else ""))

    if args.if_due and not due:
        print(f"Not due; next refresh in {REFRESH_EVERY_DAYS - age_days} days")
        return
    if args.dry_run:
        print("DRY RUN: would call GET graph.instagram.com/refresh_access_token "
              "and write the new token to .env")
        return

    resp = graph("GET", "refresh_access_token", {"grant_type": "ig_refresh_token"}, token, versioned=False)
    new_token = resp["access_token"]
    set_env_value("IG_ACCESS_TOKEN", new_token)
    t = now()
    state = {
        "refreshed_at": t.isoformat(timespec="seconds"),
        "expires_at": (t + datetime.timedelta(seconds=int(resp.get("expires_in", 0)))).isoformat(timespec="seconds"),
    }
    with open(STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)
    print(f"Refreshed token written to .env (expires {state['expires_at']})")


if __name__ == "__main__":
    try:
        main()
    except (GraphError, KeyError, OSError) as e:
        sys.exit(f"Error: {redact(e)}")
