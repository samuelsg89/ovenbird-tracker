"""Ovenbird (Singapore) reservation availability tracker.

Polls the restaurants.sg (Weeloy) booking API that powers the reservation
widget on ovenbirdsg.com, and sends a WhatsApp alert via CallMeBot whenever
the availability data changes for the configured party sizes.
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import requests

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.json"
STATE_PATH = BASE_DIR / "state.json"
LOG_PATH = BASE_DIR / "tracker.log"

API_URL = "https://www.restaurants.sg/apiv4/restaurant/dispo/dayavailable/"
BOOKING_PAGE_URL = "https://ovenbirdsg.com/?page_id=45"
RESTAURANT_ID = "SG_SG_R_OvenbirdAndHappyLily"
SGT = ZoneInfo("Asia/Singapore")

HEADERS = {
    "Content-Type": "application/json",
    "Origin": "https://www.restaurants.sg",
    "Referer": (
        "https://www.restaurants.sg/modules/booking/book_form_section.php"
        f"?redirect=1&data=&bkrestaurant={RESTAURANT_ID}&bktitle=&city=&country="
        "&bkextra=&bktracking=WEBSITE|onrequest"
    ),
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
}


def log(message: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')} {message}"
    print(line)
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line + "\n")


DEFAULT_CONFIG = {
    "party_sizes": [2, 4],
    "poll_interval_seconds": 600,
}


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        config.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))

    # Environment variables take precedence (used for GitHub Actions secrets).
    if os.environ.get("CALLMEBOT_PHONE"):
        config["callmebot_phone"] = os.environ["CALLMEBOT_PHONE"]
    if os.environ.get("CALLMEBOT_APIKEY"):
        config["callmebot_apikey"] = os.environ["CALLMEBOT_APIKEY"]

    if "callmebot_phone" not in config or "callmebot_apikey" not in config:
        log(
            "Missing CallMeBot credentials. Set callmebot_phone/callmebot_apikey in "
            f"{CONFIG_PATH}, or CALLMEBOT_PHONE/CALLMEBOT_APIKEY env vars."
        )
        sys.exit(1)

    return config


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


def fetch_availability(pers: int) -> dict | None:
    payload = {
        "restaurant": RESTAURANT_ID,
        "product": "Ovenbird",
        "time": "19:30",
        "pers": pers,
        "mealtype": "dinner",
        "platform": "waitlist",
    }
    try:
        resp = requests.post(API_URL, headers=HEADERS, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()["data"]
    except Exception as exc:
        log(f"[pers={pers}] request failed: {exc}")
        return None


def availability_by_date(availability: str, stardate: str) -> dict[str, str]:
    """Map each flag in the rolling window to its actual calendar date.

    The API's `availability` string always starts at "today" (`stardate`),
    so the same array index means a different date on every poll once the
    date rolls over. Comparisons must be keyed by date, not index.
    """
    start = datetime.strptime(stardate, "%Y-%m-%d").date()
    return {
        (start + timedelta(days=i)).isoformat(): flag
        for i, flag in enumerate(availability)
    }


def opened_dates(old_availability: str, old_stardate: str, new_availability: str, new_stardate: str) -> list[str]:
    old_map = availability_by_date(old_availability, old_stardate)
    new_map = availability_by_date(new_availability, new_stardate)
    opened = [
        date
        for date, flag in new_map.items()
        if flag == "1" and old_map.get(date) == "0"
    ]
    opened.sort()
    return opened


def dinnerdata_by_date(dinnerdata: str, stardate: str, num_days: int) -> dict[str, str]:
    """Same rolling-window-to-date remap as availability_by_date, but for the
    per-day time-slot chunks in `dinnerdata` (4 hex chars per day)."""
    chunk_len = len(dinnerdata) // num_days if num_days else 0
    start = datetime.strptime(stardate, "%Y-%m-%d").date()
    return {
        (start + timedelta(days=i)).isoformat(): dinnerdata[i * chunk_len : (i + 1) * chunk_len]
        for i in range(num_days)
    }


def changed_slot_dates(
    old_dinnerdata: str, old_stardate: str, old_num_days: int,
    new_dinnerdata: str, new_stardate: str, new_num_days: int,
    already_reported: set[str],
) -> list[str]:
    old_map = dinnerdata_by_date(old_dinnerdata, old_stardate, old_num_days)
    new_map = dinnerdata_by_date(new_dinnerdata, new_stardate, new_num_days)
    changed = [
        date
        for date, chunk in new_map.items()
        if date in old_map and chunk != old_map[date] and date not in already_reported
    ]
    changed.sort()
    return changed


def send_whatsapp(config: dict, message: str) -> None:
    phone = config["callmebot_phone"]
    apikey = config["callmebot_apikey"]
    url = (
        "https://api.callmebot.com/whatsapp.php"
        f"?phone={quote(phone)}&text={quote(message)}&apikey={quote(str(apikey))}"
    )
    try:
        resp = requests.get(url, timeout=15)
        log(f"WhatsApp send status={resp.status_code} body={resp.text[:200]!r}")
    except Exception as exc:
        log(f"WhatsApp send failed: {exc}")


def check_party_size(config: dict, state: dict, pers: int) -> None:
    key = str(pers)
    data = fetch_availability(pers)
    if data is None:
        return

    availability = data["availability"]
    iswaitlist = data["iswaitlist"]
    dinnerdata = data.get("info", {}).get("dinnerdata", "")
    stardate = data["stardate"]

    prev = state.get(key)
    if prev is None:
        state[key] = {
            "availability": availability,
            "iswaitlist": iswaitlist,
            "dinnerdata": dinnerdata,
            "stardate": stardate,
        }
        log(f"[pers={pers}] baseline captured (iswaitlist={iswaitlist}). No alert on first run.")
        return

    changes = []

    if iswaitlist != prev["iswaitlist"]:
        if iswaitlist == 0:
            changes.append("Booking mode flipped to OPEN (was wait-list-only)!")
        else:
            changes.append("Booking mode flipped to WAIT-LIST-ONLY (was open).")

    newly_opened = opened_dates(
        prev["availability"], prev["stardate"], availability, stardate
    )
    if newly_opened:
        changes.append("New day(s) show availability: " + ", ".join(newly_opened))

    changed_slots = changed_slot_dates(
        prev.get("dinnerdata", ""), prev["stardate"], len(prev["availability"]),
        dinnerdata, stardate, len(availability),
        already_reported=set(newly_opened),
    )
    if changed_slots:
        changes.append("Time-slot pattern changed on: " + ", ".join(changed_slots) + " - check the calendar.")

    if changes:
        message = (
            f"Ovenbird ({pers} pax) update:\n- " + "\n- ".join(changes) + f"\n{BOOKING_PAGE_URL}"
        )
        log(f"[pers={pers}] CHANGE DETECTED: {changes}")
        send_whatsapp(config, message)
    else:
        log(f"[pers={pers}] no change (iswaitlist={iswaitlist})")

    state[key] = {
        "availability": availability,
        "iswaitlist": iswaitlist,
        "dinnerdata": dinnerdata,
        "stardate": stardate,
    }


RELEASE_REMINDER_HOUR_SGT = 9  # Ovenbird opens new dates around 10am SGT on the 1st.


def maybe_send_release_reminder(config: dict, state: dict) -> None:
    """Ovenbird typically releases a new month of dates on the 1st at ~10am
    SGT. Send a heads-up once, ahead of that, so there's time to be ready -
    independent of whether a change has actually been detected yet."""
    now = datetime.now(SGT)
    if now.day != 1 or now.hour < RELEASE_REMINDER_HOUR_SGT:
        return

    this_month = now.strftime("%Y-%m")
    if state.get("last_release_reminder") == this_month:
        return

    message = (
        "Ovenbird heads up: new dates are usually released today (the 1st) "
        "around 10am SGT and can sell out within minutes. Keep an eye on "
        f"{BOOKING_PAGE_URL}"
    )
    log("Sending monthly release-day reminder.")
    send_whatsapp(config, message)
    state["last_release_reminder"] = this_month


def run_once(config: dict, state: dict) -> None:
    # Always changes, so state.json always has a diff to commit - keeps the
    # repo "active" for GitHub Actions (scheduled workflows auto-disable
    # after 60 days with no commits) and doubles as a heartbeat/last-run log.
    state["last_checked_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

    maybe_send_release_reminder(config, state)
    save_state(state)
    for pers in config.get("party_sizes", [2, 4]):
        check_party_size(config, state, pers)
        save_state(state)
        time.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Ovenbird SG reservation availability tracker")
    parser.add_argument("--once", action="store_true", help="Run a single check pass and exit")
    args = parser.parse_args()

    config = load_config()
    state = load_state()

    if args.once:
        run_once(config, state)
        return

    log("Ovenbird tracker started. Ctrl+C to stop.")
    while True:
        run_once(config, state)
        interval = config.get("poll_interval_seconds", 600) + random.uniform(0, 3)
        time.sleep(interval)


if __name__ == "__main__":
    main()
