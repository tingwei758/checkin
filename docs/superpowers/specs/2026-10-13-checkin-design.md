# Design: a minimal PT/BT check-in runner

Date: 2026-10-13

## Intent and why

Ten private-tracker sites each give a daily reward for a "签到" (check-in)
click, and some of them track a consecutive-day streak — one of the user's
is at 892 days. Doing this by hand across ten sites every day is the
problem. Missing a day costs the streak.

The existing `qd/` folder in the parent directory (QD, the HAR-based
request-automation framework) is the prior art and the thing to *not*
rebuild: it carries a Tornado web app, multi-user accounts, MySQL/SQLite
abstraction, HAR template editing, a public-template store, and push
channels. The user wants the small, boring version of the 5% of that
which they actually use.

Several of these sites sit behind Cloudflare. A plain `requests` call gets
challenged; the request has to present a believable browser TLS
fingerprint.

## Goals

- One daily automated check-in per configured site, at 03:20 Beijing time.
- Get past Cloudflare on the sites that have it, using TLS impersonation
  only (no browser).
- A status page showing, for every configured site: the last 7 days as
  pass/fail dots, the current streak, and the site's own reply message.
- Manual "check in now" from that page, per site and for all sites.
- Adding an eleventh site means editing a config file, not writing code.
- Replacing an expired cookie means editing one small file on the NAS,
  with no restart and no rebuild.

## Non-goals

- No browser automation (headless or headful). The user explicitly wants
  curl_cffi first and will ask for a browser engine later if the TLS
  approach proves insufficient on some site. Nothing in the design should
  make adding a browser engine later *hard*, but no browser code ships now.
- No push notifications of any kind — no Telegram, no email, no webhook.
  The status page and the container logs are the whole output surface.
- No multi-user support, no login, no accounts.
- No HAR import, no template store, no visual request editor.
- No editing of configuration or cookies through the web UI. The page is
  read-only apart from the manual-run buttons.
- No form logins. A session cookie is enough for all ten sites, so there is
  no username/password flow and no login step before the check-in request.
- No proxy support. The NAS reaches all ten sites directly.
- No catch-up of missed runs (see Constraints).
- No verification that a streak increments correctly day over day; the
  streak number is scraped and displayed as-is.

## Anti-goals

These would mean failure even if the thing technically works:

- It grows into QD. If a reader of the source needs a tour to find where
  a request gets made, the design has failed.
- A plugin system, a DB migration framework, a frontend build step, or a
  per-site Python subclass. Per-site behaviour lives in config data.
- Silent failure. If a cookie expired three weeks ago, that has to be
  obvious the moment the page is open, not buried in a log file.

## Constraints

- Runs as a single Docker container on the user's NAS.
- Timezone is Asia/Shanghai, baked into the image, so 03:20 means 03:20
  regardless of the host clock.
- Status page is LAN-only with no authentication. This is the user's call,
  made knowing the manual-run buttons let anyone who can reach the port
  fire check-ins. Do not add auth; do not expose the port publicly.
- Roughly ten sites. Nothing needs to scale past a few dozen.
- The user edits config and cookie files directly on the NAS (File
  Station / SSH), so both files are mounted from a host directory and must
  be hand-editable and comfortable to read.

## What the user decided

### The check itself

Each site is **one GET to a fixed URL**, carrying a session cookie the user
supplies. Confirmed examples:

- `https://hhanclub.net/attendance.php` → reply contains
  `这是您的第264次签到，已连续签到1天，本次签到获得10个憨豆。你目前拥有补签卡37张`
- `https://hdfans.org/attendance.php` → reply contains
  `签到成功` then `这是您的第 1314 次签到，已连续签到 892 天，本次签到获得 100 个魔力值。…`

Note the wording and the whitespace differ between sites (`第264次` vs
`第 1314 次`), so matching and extraction are per-site config, never a
single global rule.

### Three outcomes, not two

1. **Success** — the success pattern matched. Store the extracted message.
2. **Already checked in** — e.g. `你今天已经签到过了`. The day's work is
   done; the day counts as fine, but is distinguishable from a fresh
   success in the UI (amber dot in the mockup).
3. **Failure** — everything else: a login page instead of content (cookie
   expired), a Cloudflare challenge or 403, site down, timeout.

The reply message matters as much as the outcome. The page shows the
site's own sentence, not just a tick.

### Retries

On failure, retry at **+15 minutes** and **+1 hour** — two retries, three
attempts total — then stop for the day. Rationale from the user: if it
isn't a transient busy-server blip, retrying won't fix it. Every attempt
is recorded and visible ("3 attempts" in the mockup).

### Schedule

03:20 Beijing time daily, with a **per-site random jitter** so the ten
requests don't leave at the same instant.

**No catch-up.** If the NAS was off or the container was down at 03:20,
that day is simply skipped. The user was told this can cost a long streak
after an overnight reboot and chose it anyway.

### Streak

Scrape the consecutive-day number out of the reply message (per-site
pattern) and show it on the page. No cross-day consistency checking.

### The status page

Site-per-row, which the user chose over a day-by-day log. Mockups are in
`.superpowers/brainstorm/*/content/status-page.html` and
`status-page-v2.html` (the approved one is v2). It shows:

- Header: count of configured sites, how many are OK today, the next run
  time and countdown, and a **"Check in all now"** button.
- One row per **configured** site — including sites that have never run
  (hollow dots, "never run") and sites disabled in config ("paused").
  The row list comes from config, not from history.
- Columns: site name, last 7 days as coloured dots, streak, last result
  (the site's message, or the failure reason plus attempt count), and a
  per-row **`run`** button.
- Failed rows are tinted so they're findable at a glance.
- After a manual run, a banner reports what happened.

Server-rendered, refresh to update. No JS framework, no build step.

The day-by-day detail — every attempt, with timing and reasons — goes to
**stdout** only, where `docker logs` and the Synology log viewer can read
it. It is deliberately not a web view.

## The how, as decided

- **Python 3.12.**
- **`curl_cffi`** for all HTTP, with Chrome impersonation. Per-site
  override of the impersonation target is available in config.
- **`APScheduler`** for the daily trigger and the retry scheduling.
- **Flask + one Jinja template** for the page.
- **SQLite** for history: one row per attempt. The dots, the streak and
  the attempt counts are queries, not maintained counters. Retention 90
  days; the page shows 7.
- **Two config files**, mounted at `/config`:
  - `config.yaml` — the site list: name, URL, success pattern, already-done
    pattern, streak pattern, optional impersonate override, optional
    enabled flag.
  - `cookies.yaml` — just `name: cookie string`. Separate from
    `config.yaml` on purpose: the file the user touches a few times a year
    stays small enough to open and edit without scrolling past anything
    else.
  - Both re-read at the start of every run, so replacing a cookie needs no
    restart.
- **SQLite file** at `/data`.
- **One image, one process.** `python:3.12-slim`, `TZ=Asia/Shanghai`, two
  volumes, one exposed port.
- **Shape of the source**: a small package — config loading, fetching,
  per-site check logic, storage, web app, entrypoint. Target around 500
  lines. No plugin system, no migrations.

## Calls I made (flagging them so they can be overruled while reading)

- Project lives in `checkin/` next to the existing `qd/` folder, confirmed
  by the user; they will copy the folder to the NAS to deploy it. It is
  developed on macOS, so it must be runnable locally as a plain process as
  well as in the container.
- Jitter window: 0–20 minutes after 03:20, drawn per site per day.
- Retention of 90 days of attempt history.
- The "already checked in" outcome keeps the day green-ish but visually
  distinct (amber), rather than counting as a failure.
- No authentication on the page, per the LAN-only constraint.
- Manual runs use the same code path as scheduled runs, and do not
  schedule retries — a manual run is one attempt, reported immediately.
- "Today" means the Asia/Shanghai calendar day, for the dots and for the
  "already checked in" logic alike.
- A site is attempted at most once successfully per day: once a run ends in
  success or already-checked-in, nothing further is scheduled that day.
- Config allows optional extra headers per site (notably User-Agent), since
  some trackers tie a session to the browser that created it and the cookie
  the user pastes came from a real browser.
- A 200 response matching neither the success nor the already-done pattern
  is a failure, with a short excerpt of the response recorded so the reason
  is diagnosable from the page.

## Left to the builder

- Exact internal module boundaries and function signatures.
- SQLite schema details and indexing.
- HTTP timeout values and whether retries differ for timeout vs 403.
- How patterns are expressed in YAML (plain regex is assumed) and how the
  message is trimmed for display.
- The port number and the exact HTML/CSS, within the approved layout.
- Logging format on stdout.
- How a manual "run all" is executed (sequential is fine at this scale).
