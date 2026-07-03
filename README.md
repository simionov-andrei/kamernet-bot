# Kamernet alert bot

Polls Kamernet for new listings that match your preferences and pushes an
**instant Telegram notification** to your phone — with the listing link and a
ready-to-paste reply — so you can respond within seconds.

## How it works

```
scraper.py   → scrapes Kamernet search pages (cloudscraper + BeautifulSoup)
matcher.py   → keeps only the ones matching config.yaml
state.py     → remembers what it already saw, so "new" means new
notifier.py  → sends you a Telegram push for each new match
main.py      → ties it together (run once, loop forever, or mock-test)
```

## Why notify instead of auto-message the landlord

You _could_ try to fully automate messaging landlords, but on Kamernet that
needs a **paid tenant subscription**, it **violates their Terms of Service**,
and their Cloudflare/anti-bot layer can get that paid account **banned**. A
phone push lets you fire off a personal reply in ~5 seconds, which is fast
enough to compete and keeps your account safe. That's why this is built
notify-first. The hook where auto-send _would_ go is left in `notifier.py` with
a clear warning, unimplemented on purpose.

## Setup

1. **Install and test locally** (the mock test needs no network or accounts):

   ```bash
   pip install -r requirements.txt
   python -m kamernet_bot.main mock
   ```

   You should see it match 1 of the 3 fake listings.

2. **Set up Telegram** — see the header comment in `kamernet_bot/notifier.py`.
   You'll end up with a `TELEGRAM_TOKEN` and `TELEGRAM_CHAT_ID`.

3. **Set your search URLs** in `config.yaml` under `search_urls`. Build each
   search in the browser (city, type, max rent, min size), then copy the
   resulting URL. For your per-type caps, use one URL per type with its own
   `maxRent` (a studios-... URL capped at 1350, a rooms-... URL capped at 800),
   so Kamernet filters server-side and `matcher.py` just refines.

4. **Edit `config.yaml`** preferences (cities, per-type caps, area, message).
   Note: keyword filters only match the search-card text, since the full
   listing description lives on the detail page.

Run a real cycle locally:

```bash
export TELEGRAM_TOKEN=...    # on Windows: set TELEGRAM_TOKEN=...
export TELEGRAM_CHAT_ID=...
python -m kamernet_bot.main once
```

## Running it free & continuously — pick one

### Option A — GitHub Actions (easiest, zero server to manage)

Truly free, no server, no uptime worries. Polls on a schedule (min every
5 min; runs can be delayed a bit under load).

1. Push this folder to a **private** GitHub repo.
2. Repo → Settings → Secrets and variables → Actions → add `TELEGRAM_TOKEN`
   and `TELEGRAM_CHAT_ID`.
3. That's it — `.github/workflows/poll.yml` runs every 5 minutes and commits
   `seen_ids.json` back so it remembers what it saw between runs.

Trade-off: 5-minute floor, so not second-by-second.

### Option B — Oracle Cloud "Always Free" VM (truly continuous, faster)

A real always-on Linux VM that never sleeps, free indefinitely. Best if you
want tight polling (e.g. every 15s) to beat other applicants.

```bash
# On the VM, after cloning + configuring:
pip install -r requirements.txt
export TELEGRAM_TOKEN=... TELEGRAM_CHAT_ID=...
nohup python -m kamernet_bot.main loop &          # or make a systemd service
```

Set `poll_interval_seconds` in `config.yaml` to how often you want to check.
A systemd unit is the robust way to keep it running/restarting — ask if you
want one written out.

### Other options

- **Fly.io** free allowance can run a small always-on process (similar to B).
- **PythonAnywhere** free tier runs scheduled tasks but only ~once/day on the
  free plan — too slow for this.
- **Render / Railway** free tiers either sleep on inactivity or are trial
  credits now, so they're not ideal for an always-on poller.

> Free tiers change often — double-check current limits before committing.

## Please be a good citizen

- Poll gently (every 60s is plenty; don't hammer the site every second).
- This is for your own personal search. Don't message people you're not
  genuinely interested in renting from.
- Scraping and automation may be against Kamernet's Terms; you're responsible
  for how you use this.
