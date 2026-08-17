import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


LISTINGS_URL = (
    "https://plaza.newnewnew.space/en/availables-places/living-place"
    "#?gesorteerd-op=zoekprofiel&locatie=Amsterdam-Nederland%2B-%2BNoord-Holland"
)

# --- Login credentials -----------------------------------------------------
# Prefer environment variables for credentials (safer than hardcoding).
PLAZA_EMAIL = os.environ.get("PLAZA_EMAIL")
PLAZA_PASSWORD = os.environ.get("PLAZA_PASSWORD")

CARD_SELECTOR = "div[id^='object-tile-']"
LINK_SELECTOR = "a[href*='/en/availables-places/living-place/details/']"
TITLE_SELECTOR = None   # use link text or parse address separately

# --- Login page selectors ---------------------------------------------------
# PLACEHOLDERS: the login form is rendered client-side by the Angular app,
# so I can't read its real DOM without a live browser. Run:
#   python plaza_bot.py --debug-login
# then open login_page.html / login_page.png (saved next to this script)
# and update these four selectors to match what you actually see.
LOGIN_TRIGGER_SELECTOR = "zds-navigation-link[aria-label=\"Login\"]"   # navigation link that opens the login form
LOGIN_EMAIL_SELECTOR = "input[name=\"username\"]"
LOGIN_PASSWORD_SELECTOR = "input[name=\"password\"]"
# Try common button selectors first; script will fall back to pressing Enter in the password field.
LOGIN_SUBMIT_SELECTOR = (
    "button:has-text(\"Login\")"
    ", button:has-text(\"Log in\")"
    ", input[type='submit']"
    ", button[type='submit']"
)
# Account link / overview visible when logged in (NL/EN paths)
LOGIN_SUCCESS_SELECTOR = (
    "zds-link-cta[link*=\"mijn-pagina\"], zds-link-cta[link*=\"my-page\"],"
    " text=/Account|Mijn overzicht/i"
)

# --- Reageer (react/apply) selectors ----------------------------------------
REAGEER_BUTTON_SELECTOR = "input.reageer-button"
# If a listing requires a motivation text before you can react, the button
# above won't be present (see ng-if="!object.reactionData.kanMotiveren" in
# the HTML you gave me). I don't have the selectors for that alternate flow,
# so the bot detects that case and skips + notifies you rather than guessing.
MOTIVATION_REQUIRED_HINT_SELECTOR = "textarea, [class*='motiveer' i]"

NTFY_TOPIC = "OurDomain_Studio_andreisimi7742"
STATE_FILE = Path(__file__).with_name("plaza_seen_listings.json")
CHECK_INTERVAL_SECONDS = 3
RELOGIN_INTERVAL_SECONDS = 10 * 60   # refresh the login session every 10 minutes
WAIT_AFTER_LOAD_MS = 4000            # extra wait for the JS-rendered list to settle
WAIT_AFTER_DETAIL_LOAD_MS = 3000     # extra wait for a listing detail page to settle


def send_notification(title: str, url: str, timestamp: str, reacted: bool, note: str = ""):
    status = "Auto-reacted ✅" if reacted else "Reaction NOT sent ⚠️"
    message = f"{title}\n{status}\n{note}\nTime: {timestamp}\n{url}".strip()
    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=message.encode("utf-8"),
        headers={
            "Title": "New Plaza listing!",
            "Priority": "high",
            "Tags": "house,white_check_mark" if reacted else "house,warning",
        },
    )


def load_seen() -> set:
    if STATE_FILE.exists():
        return set(json.loads(STATE_FILE.read_text()))
    return set()


def save_seen(seen: set):
    STATE_FILE.write_text(json.dumps(sorted(seen)))


def login(page, debug: bool = False) -> bool:
    """Log in to Plaza. Returns True if login looked successful."""
    page.goto(LISTINGS_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(2000)

    # Try several possible login trigger selectors (site may render different elements).
    trigger_candidates = [
        LOGIN_TRIGGER_SELECTOR,
        "zds-navigation-link[aria-label=\"Login\"]",
        "zds-navigation-link:has-text(\"Login\")",
        "text=/login|inloggen|sign in/i",
        "a[aria-label=\"Login\"]",
    ]

    clicked = False
    # Ensure we're on the listings page before opening the login UI
    try:
        page.goto(LISTINGS_URL, wait_until="networkidle", timeout=60000)
    except Exception:
        pass

    for sel in trigger_candidates:
        try:
            page.wait_for_selector(sel, timeout=3000)
            page.click(sel, timeout=5000)
            page.wait_for_timeout(1500)
            clicked = True
            break
        except Exception:
            continue

    if not clicked:
        print("Could not find the login trigger link — check LOGIN_TRIGGER_SELECTOR or page structure.")
        # Fallback: navigate directly to known portal/login paths instead of
        # relying on a navigation link that may not be rendered yet.
        fallback_paths = [
            "/en/my-page/account",
            "/en/my-page/account?logintype=login",
            "/redirect?code=portal-login-page",
        ]
        base = "https://plaza.newnewnew.space"
        for p in fallback_paths:
            try:
                print(f"Attempting direct navigation to login fallback: {p}")
                page.goto(base + p, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(1500)
                # quick check whether we reached a page that contains a login input
                if page.query_selector(LOGIN_EMAIL_SELECTOR) or page.query_selector(LOGIN_PASSWORD_SELECTOR):
                    clicked = True
                    break
            except Exception:
                continue

    if debug:
        Path("login_page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path="login_page.png", full_page=True)
        print("Saved login_page.html and login_page.png — inspect these to fix the "
              "LOGIN_* selectors at the top of the script.")
        return False

    # Ensure credentials are provided
    if not PLAZA_EMAIL or not PLAZA_PASSWORD:
        print("PLAZA_EMAIL and/or PLAZA_PASSWORD not set in environment; cannot login.")
        return False

    # Wait for the username input to appear (login UI may be client-rendered)
    try:
        # Give the client-side app more time to render the login form.
        page.wait_for_selector(LOGIN_EMAIL_SELECTOR, timeout=30000)
        page.fill(LOGIN_EMAIL_SELECTOR, PLAZA_EMAIL, timeout=5000)
        page.fill(LOGIN_PASSWORD_SELECTOR, PLAZA_PASSWORD, timeout=5000)
    except PlaywrightTimeoutError as e:
        # Save debug artifacts to help diagnose selector mismatches
        try:
            Path("login_page_timeout.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path="login_page_timeout.png", full_page=True)
            print("Saved login_page_timeout.html and login_page_timeout.png for inspection.")
        except Exception:
            pass
        print("Login form fields didn't match — update LOGIN_* selectors. Error:", e)
        return False

    # Try clicking a submit button; if none found, press Enter in the password field as a fallback.
    try:
        page.click(LOGIN_SUBMIT_SELECTOR, timeout=4000)
    except Exception:
        try:
            page.press(LOGIN_PASSWORD_SELECTOR, "Enter")
        except Exception:
            print("Could not find or activate a login submit control — update LOGIN_SUBMIT_SELECTOR.")
            return False

    page.wait_for_timeout(3000)

    # Try several possible success indicators (localized paths or visible text).
    try:
        page.wait_for_selector("zds-link-cta[link*='mijn-pagina']", timeout=4000)
        print("Login looks successful (found mijn-pagina link).")
        return True
    except PlaywrightTimeoutError:
        pass

    try:
        page.wait_for_selector("zds-link-cta[link*='my-page']", timeout=4000)
        print("Login looks successful (found my-page link).")
        return True
    except PlaywrightTimeoutError:
        pass

    try:
        page.wait_for_selector("text=/Account|Mijn overzicht/i", timeout=4000)
        print("Login looks successful (found account/overview text).")
        return True
    except PlaywrightTimeoutError:
        pass
    except PlaywrightTimeoutError:
        # Save the post-login DOM and screenshot for inspection to help
        # diagnose selector or credential issues.
        try:
            Path("post_login.html").write_text(page.content(), encoding="utf-8")
            page.screenshot(path="post_login.png", full_page=True)
            print("Saved post_login.html and post_login.png for inspection.")
        except Exception:
            pass
        print("Couldn't confirm login succeeded — update LOGIN_SUCCESS_SELECTOR, or check credentials.")
        return False


def react_to_listing(context, href: str) -> tuple[bool, str]:
    """Open a listing detail page in a new tab and click Reageer.

    Returns (reacted: bool, note: str).
    """
    detail_page = context.new_page()
    try:
        detail_page.goto(href, wait_until="networkidle", timeout=60000)
        detail_page.wait_for_timeout(WAIT_AFTER_DETAIL_LOAD_MS)

        button = detail_page.query_selector(REAGEER_BUTTON_SELECTOR)
        if button:
            button.click()
            detail_page.wait_for_timeout(2000)
            return True, "Clicked Reageer button."

        if detail_page.query_selector(MOTIVATION_REQUIRED_HINT_SELECTOR):
            return False, ("This listing needs a motivation text to react — no "
                            "selectors configured for that flow, skipped.")

        return False, "Reageer button not found on the page (selector may be stale)."
    except PlaywrightTimeoutError as e:
        return False, f"Timed out loading listing page: {e}"
    finally:
        detail_page.close()


def fetch_listings(page, debug: bool = False):
    """Load the page in a real browser and return list of (id_url, title)."""
    page.goto(LISTINGS_URL, wait_until="networkidle", timeout=60000)
    page.wait_for_timeout(WAIT_AFTER_LOAD_MS)

    if debug:
        Path("rendered_page.html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path="rendered_page.png", full_page=True)
        print("Saved rendered_page.html and rendered_page.png for inspection.")

    cards = page.query_selector_all(CARD_SELECTOR)
    listings = []

    for card in cards:
        link_el = card.query_selector(LINK_SELECTOR)
        href = link_el.get_attribute("href") if link_el else None
        if not href:
            continue
        if href.startswith("/"):
            href = "https://plaza.newnewnew.space" + href

        if TITLE_SELECTOR:
            title_el = card.query_selector(TITLE_SELECTOR)
            title = title_el.inner_text().strip() if title_el else href
        else:
            title = (link_el.inner_text().strip() if link_el else href) or href

        listings.append((href, title))

    return listings


def run_once(page, context, seen: set, debug: bool = False, auto_react: bool = True):
    listings = fetch_listings(page, debug=debug)

    if debug:
        print(f"Found {len(listings)} card(s) with selector '{CARD_SELECTOR}'")
        for href, title in listings:
            print("  -", title, "->", href)
        return seen  # don't notify in debug mode

    current_ids = {href for href, _ in listings}
    new_ids = current_ids - seen

    if new_ids:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for href, title in listings:
            if href in new_ids:
                print("NEW LISTING:", title, href)
                reacted, note = (False, "Auto-react disabled")
                if auto_react:
                    reacted, note = react_to_listing(context, href)
                    print("  ->", note)
                send_notification(title, href, now, reacted, note)

    seen = current_ids
    save_seen(seen)
    return seen


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Run once, dump rendered HTML/screenshot and found cards, then exit (no notifications, no login).",
    )
    parser.add_argument(
        "--debug-login",
        action="store_true",
        help="Open the login flow, dump login_page.html/png, then exit. Use this to fix the LOGIN_* selectors.",
    )
    parser.add_argument(
        "--test-login",
        action="store_true",
        help="Attempt a real login once, report success/failure, then exit.",
    )
    parser.add_argument(
        "--no-react",
        action="store_true",
        help="Just notify on new listings, don't auto-click Reageer.",
    )
    parser.add_argument(
        "--test-one",
        nargs="?",
        const="https://plaza.newnewnew.space/aanbod/huurwoningen/details/15191-universittsstrae-114-b0916-bochum",
        default=None,
        metavar="URL",
        help=(
            "Log in, then run the real react_to_listing() flow against a single "
            "listing URL (defaults to the Bochum example) and report the result. "
            "This WILL submit a real Reageer click if the button is found — only "
            "use it on a listing you actually want to react to. Exits after one attempt."
        ),
    )
    args = parser.parse_args()

    seen = load_seen()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        )
        page = context.new_page()

        if args.debug_login:
            login(page, debug=True)
            browser.close()
            return

        if args.test_one:
            url = args.test_one
            print(f"--test-one: logging in, then attempting Reageer on:\n  {url}")
            logged_in = login(page, debug=False)
            if not logged_in:
                print("Login failed or unconfirmed — aborting before touching the listing. "
                      "Run --debug-login / --test-login first to fix selectors.")
                browser.close()
                return
            reacted, note = react_to_listing(context, url)
            print("TEST-ONE RESULT:", "REACTED" if reacted else "NOT REACTED", "-", note)
            browser.close()
            return

        if args.test_login:
            success = login(page, debug=False)
            print("TEST LOGIN RESULT:", "SUCCESS" if success else "FAILURE")
            browser.close()
            return

        

        if args.debug:
            run_once(page, context, seen, debug=True)
            browser.close()
            return

        logged_in = login(page, debug=False)
        if not logged_in:
            print("WARNING: proceeding without confirmed login — Reageer clicks will "
                  "likely fail until LOGIN_* selectors are fixed (run --debug-login).")
        last_login_time = time.monotonic()

        while True:
            if time.monotonic() - last_login_time >= RELOGIN_INTERVAL_SECONDS:
                print("Refreshing login session...")
                try:
                    logged_in = login(page, debug=False)
                    if not logged_in:
                        print("WARNING: periodic re-login did not confirm success.")
                except Exception as e:
                    print("Failed to re-login:", e)
                last_login_time = time.monotonic()

            try:
                print("Checking:", LISTINGS_URL)
                seen = run_once(page, context, seen, debug=False, auto_react=not args.no_react)
            except Exception as e:
                print("Failed to check listings:", e)

            time.sleep(CHECK_INTERVAL_SECONDS)


if __name__ == "__main__":
    main()