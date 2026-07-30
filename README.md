# Kamernet + Pararius alert bots

Polls Kamernet and Pararius for new listings that match your preferences and
pushes an **instant Telegram notification** to your phone — with the listing
link and a ready-to-paste reply — so you can respond within seconds.

There are two independent bots in this repo, one per site, each with its own
config, state file, and Telegram bot (so alerts don't get mixed into one chat):

| Site     | Package         | Config                | State file              | Env vars |
|----------|-----------------|-----------------------|--------------------------|----------|
| Kamernet | `kamernet_bot/` | `config.yaml`         | `seen_ids.json`          | `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` |
| Pararius | `pararius_bot/` | `pararius_config.yaml`| `pararius_seen_ids.json` | `PARARIUS_TELEGRAM_TOKEN`, `PARARIUS_TELEGRAM_CHAT_ID` |

## How it works (same shape for both)

```
scraper.py   → scrapes the site's search pages (cloudscraper + BeautifulSoup)
matcher.py   → keeps only the ones matching the config
state.py     → remembers what it already saw, so "new" means new
notifier.py  → sends you a Telegram push for each new match
main.py      → ties it together (run once, loop forever, or mock-test)
```

Run either one the same way, just swap the module:

```bash
python -m kamernet_bot.main mock
python -m pararius_bot.main mock
```

> Note on `pararius_bot/scraper.py`: its selectors are based on Pararius's
> long-standing public markup, not a live inspection (this environment
> couldn't reach pararius.com to verify). If it stops finding listings,
> open a search page in devtools and adjust `CARD_SELECTOR` / the
> `[class*=…]` lookups near the top of the file.

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

2. **Set up Telegram** — see the header comment in `kamernet_bot/notifier.py`
   (Kamernet) and `pararius_bot/notifier.py` (Pararius). These must be **two
   different bots** from @BotFather so alerts don't mix into one chat.
   You'll end up with `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` and
   `PARARIUS_TELEGRAM_TOKEN`/`PARARIUS_TELEGRAM_CHAT_ID`. Put all four into
   `.env` (see the placeholders already there).

3. **Set your search URLs** in `config.yaml` (Kamernet) and
   `pararius_config.yaml` (Pararius) under `search_urls`. Build each search in
   the browser (city, type, max rent, min size), then copy the resulting URL.
   For Kamernet's per-type caps, use one URL per type with its own `maxRent`
   (a studios-... URL capped at 1350, a rooms-... URL capped at 800), so
   Kamernet filters server-side and `matcher.py` just refines.

4. **Edit the config** preferences (cities, per-type caps, area, message) in
   whichever of `config.yaml` / `pararius_config.yaml` applies.
   Note: keyword filters only match the search-card text, since the full
   listing description lives on the detail page.

Run a real cycle locally:

```bash
export TELEGRAM_TOKEN=...    # on Windows: set TELEGRAM_TOKEN=...
export TELEGRAM_CHAT_ID=...
python -m kamernet_bot.main once

export PARARIUS_TELEGRAM_TOKEN=...
export PARARIUS_TELEGRAM_CHAT_ID=...
python -m pararius_bot.main once
```

## Running it free & continuously — pick one

### Option A — GitHub Actions (easiest, zero server to manage)

Truly free, no server, no uptime worries. Polls on a schedule (min every
5 min; runs can be delayed a bit under load).

1. Push this folder to a **private** GitHub repo.
2. Repo → Settings → Secrets and variables → Actions → add `TELEGRAM_TOKEN`,
   `TELEGRAM_CHAT_ID`, `PARARIUS_TELEGRAM_TOKEN`, and `PARARIUS_TELEGRAM_CHAT_ID`.
3. That's it — `.github/workflows/poll.yml` (Kamernet) and
   `.github/workflows/poll_pararius.yml` (Pararius) each run every 5 minutes
   and commit their own state file (`seen_ids.json` / `pararius_seen_ids.json`)
   back so they remember what they've seen between runs.

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
