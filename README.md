# checkin

A small daily 签到 (check-in) runner for private-tracker sites, including the
ones behind Cloudflare. One container, one process: a scheduler that checks in
once a day and a single status page that shows what happened.

Design: [`docs/superpowers/specs/2026-10-13-checkin-design.md`](docs/superpowers/specs/2026-10-13-checkin-design.md)

## What it does

- Checks in once a day at 03:20 Asia/Shanghai, each site at its own random
  offset within 20 minutes so the requests don't leave together.
- On failure, retries at +15 minutes and +1 hour, then stops for the day.
- Gets past Cloudflare with [curl_cffi](https://github.com/lexiforest/curl_cffi)
  TLS impersonation — no browser.
- Keeps every attempt in SQLite and shows the last 7 days, the streak, and the
  site's own reply message on one page.

## Configure

Two files in `config/`, both copied from the `.example.yaml` versions:

- `config.yaml` — the site list: URL, the patterns that recognise success,
  "already checked in", and the streak number.
- `cookies.yaml` — one line per site: `sitename: "cookie header string"`.
  Copy the cookie from your browser's devtools (Network → the request →
  Request Headers → Cookie).

Both files are re-read before every run, so replacing an expired cookie takes
effect without a restart. Neither is committed — see `.gitignore`.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt

# check one site right now and print the result
CHECKIN_CONFIG=config/config.yaml CHECKIN_COOKIES=config/cookies.yaml \
  CHECKIN_DB=data/checkin.sqlite .venv/bin/python -m checkin --run-now hhanclub

# scheduler + status page on http://localhost:18320
CHECKIN_CONFIG=config/config.yaml CHECKIN_COOKIES=config/cookies.yaml \
  CHECKIN_DB=data/checkin.sqlite .venv/bin/python -m checkin
```

`--run-now` exits 0 when every check was fine, 1 on a config problem, 2 for an
unknown site name, 3 when a check-in failed — handy if you ever want to wrap it
in a cron job instead.

Paths default to `/config/config.yaml`, `/config/cookies.yaml` and
`/data/checkin.sqlite` (the container layout); `CHECKIN_HOST` and
`CHECKIN_PORT` default to `0.0.0.0:18320`.

## Run in Docker

```bash
docker compose up -d --build
```

`./config` and `./data` are mounted into the container; the page is on port
18320. The image sets `TZ=Asia/Shanghai`, so 03:20 means 03:20 whatever the
host clock says.

The page has no authentication and its buttons fire real requests — keep it on
your LAN.

## Tests

```bash
.venv/bin/python -m pytest
```
