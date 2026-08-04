# Ovenbird SG Availability Tracker

Watches Ovenbird's (ovenbirdsg.com) reservation calendar for 2-pax and 4-pax
bookings and sends a WhatsApp message when:

- Booking mode flips between wait-list-only and open
- A day that was previously unavailable shows availability
- The time-slot pattern on a known day shifts
- It's the 1st of the month (~9am SGT) — a heads-up ahead of Ovenbird's usual
  ~10am release of a new month of dates, since those can sell out in minutes

It talks directly to the booking API behind the scenes (`restaurants.sg`,
Weeloy's platform) rather than scraping rendered HTML.

Runs on a schedule via **GitHub Actions** (every 10 minutes) so it works
24/7 without depending on your own machine staying on or awake.

## How it runs

- `.github/workflows/tracker.yml` triggers `python tracker.py --once` every
  10 minutes on GitHub's infrastructure.
- Credentials come from GitHub repo secrets (`CALLMEBOT_PHONE`,
  `CALLMEBOT_APIKEY`), not a committed file.
- `state.json` (what was seen on the last poll) is committed back to the
  repo by the workflow after each run, since GitHub Actions runners are
  stateless between runs — this is how it remembers what changed.

## Local development / testing

1. Copy `config.example.json` to `config.json` and fill in your CallMeBot
   phone/API key (see below). This file is gitignored — never commit it.
2. `pip install -r requirements.txt`
3. `python tracker.py --once` — single check-and-exit pass, useful for testing.
4. `python tracker.py` — runs continuously with its own internal sleep loop,
   if you want to run it locally instead of via GitHub Actions.

`check_status.bat` / `check_status.ps1` show whether a locally-run instance
is alive and how fresh its last poll was.

## CallMeBot setup (one-time, ~2 minutes)

CallMeBot is a free personal WhatsApp notification service.

1. Save this contact to your phone: **+34 684 783 347**.
2. Send it a WhatsApp message with exactly this text: `I allow callmebot to send me messages`
3. Wait for the reply — it contains your **API key**.

Note: CallMeBot occasionally rotates this number. If the message doesn't
activate within a few minutes, check the current number at
[callmebot.com/blog/free-api-whatsapp-messages](https://www.callmebot.com/blog/free-api-whatsapp-messages/).

## Notes / limits

- This only detects changes visible on the booking calendar itself. Ovenbird
  says ad-hoc cancellations are sometimes announced only via Instagram/Facebook
  Stories rather than reflected in the calendar — this tool can't see those.
- GitHub's scheduled workflows aren't guaranteed to the minute (can lag under
  load), so treat the monthly release reminder as "watch now," not "the exact
  second dates dropped."
- The API contract here was reverse-engineered from the public booking widget
  and isn't an official/documented interface, so it could change without
  notice if Weeloy updates their platform.
