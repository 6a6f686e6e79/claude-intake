"""Fill the intake form with dummy data and capture per-tab screenshots.

Dummy persona: "Riley Quinn" — entirely fictional, no relation to the user.
Pets, kids, etc. all use fresh invented names.

Self-launches Flask against a temp memory dir so the form starts empty,
regardless of the user's real ~/.claude/memory state. A defensive
clear_form() also runs before any filler as a second layer.
"""

import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:5001/"
OUT = Path(__file__).parent.parent / "screenshots"
OUT.mkdir(exist_ok=True)

VIEWPORT = {"width": 1280, "height": 900}

TABS = ["personal", "family", "work", "pets", "health", "hobbies", "identity", "goals", "comms"]


def wait_for_server(url, timeout=10):
    start = time.time()
    while time.time() - start < timeout:
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except (urllib.error.URLError, ConnectionError):
            time.sleep(0.2)
    return False


def clear_form(page):
    """Reset every interactive control to its empty state.

    Defense in depth — the temp-dir Flask launch should already ensure
    no real data hydrates, but if that's ever bypassed by accident this
    keeps the persona fictional.
    """
    page.evaluate("""
      () => {
        document.querySelectorAll(
          'input[type="text"], input[type="date"], input[type="month"], textarea'
        ).forEach(el => { el.value = ''; });
        document.querySelectorAll('select').forEach(el => { el.selectedIndex = 0; });
        document.querySelectorAll('.chip.selected')
          .forEach(c => c.classList.remove('selected'));
        document.querySelectorAll('input[type="hidden"][id$="-value"]')
          .forEach(el => { el.value = ''; });
        ['children-group', 'pets-group', 'prior-employers-group'].forEach(id => {
          const g = document.getElementById(id);
          if (g) g.innerHTML = '';
        });
      }
    """)


def fill_personal(page):
    page.fill('input[name="personal.name"]', "Riley Quinn")
    page.fill('input[name="personal.preferred_name"]', "Riley")
    page.fill('input[name="personal.birthday"]', "1989-07-14")
    page.fill('input[name="personal.city"]', "Boulder")
    page.fill('input[name="personal.state"]', "CO")
    page.fill('input[name="personal.country"]', "USA")
    page.select_option('select[name="personal.timezone"]', label="Mountain (MT)")
    page.fill(
        'textarea[name="freeform"]',
        "Moved to Boulder from Minneapolis in 2019. Two cups of coffee a day, no more. "
        "Learning to roast my own beans. I think best on long walks. Big into trail running "
        "and slowly working through the 14ers. Quiet during heavy work weeks, social on "
        "weekends."
    )


def fill_family(page):
    page.select_option('select[name="family.relationship_status"]', label="Married")
    page.fill('input[name="family.partner_name"]', "Morgan Hale")
    page.fill('input[name="family.partner_birthday"]', "1990-03-22")

    # Add two children
    page.click('button:has-text("+ Add a child")')
    page.click('button:has-text("+ Add a child")')

    page.fill('input[name="family.children[0].name"]', "Sienna")
    page.fill('input[name="family.children[0].birthday"]', "2017-05")
    page.select_option('select[name="family.children[0].status"]', value="Living")

    page.fill('input[name="family.children[1].name"]', "Wren")
    page.fill('input[name="family.children[1].birthday"]', "2020-11")
    page.select_option('select[name="family.children[1].status"]', value="Living")

    page.fill('input[name="family.siblings"]', "Brother Felix (36) in Portland, Sister Nora (31) in Chicago")
    page.fill('input[name="family.parents"]', "Mom Ellen in Madison, WI. Dad Roger in Madison, WI.")
    page.fill(
        'textarea[name="family.other"]',
        "Grandma Beatrice (94) still lives in her own home — we visit twice a year. "
        "Family does a big lake weekend every July."
    )


def fill_work(page):
    page.fill('input[name="work.title"]', "Staff Data Engineer")
    page.fill('input[name="work.company"]', "Northwind Logistics")
    page.fill('input[name="work.industry"]', "Supply chain / SaaS")
    page.fill('input[name="work.years_exp"]', "11")
    page.select_option('select[name="work.work_style"]', label="Remote")
    page.fill(
        'textarea[name="work.notes"]',
        "Lead the warehouse-events pipeline team (4 ICs). On-call rotation every 6 weeks. "
        "Side gig: occasional contract work building dbt models for a friend's analytics agency."
    )


def fill_pets(page):
    page.click('button:has-text("+ Add a pet")')
    page.click('button:has-text("+ Add a pet")')

    # Pet 1
    page.fill('input[name="pets[0].name"]', "Maple")
    page.select_option('select[name="pets[0].species"]', label="Dog")
    page.fill('input[name="pets[0].breed"]', "Australian Shepherd")
    page.fill('input[name="pets[0].birthday"]', "2021-04")
    page.select_option('select[name="pets[0].status"]', value="Still with us")

    # Pet 2
    page.fill('input[name="pets[1].name"]', "Pickle")
    page.select_option('select[name="pets[1].species"]', label="Cat")
    page.fill('input[name="pets[1].breed"]', "Domestic Shorthair")
    page.fill('input[name="pets[1].birthday"]', "2019-09")
    page.select_option('select[name="pets[1].status"]', value="Still with us")


def click_chips(page, grid_id, labels):
    for label in labels:
        # Click the chip whose text matches exactly within the named grid
        page.locator(f'#{grid_id} .chip', has_text=label).first.click()


def fill_health(page):
    page.fill('input[name="health.dietary"]', "Mostly vegetarian, eats fish a couple times a month")
    page.fill('input[name="health.allergies"]', "Tree nuts (mild), cat dander (mild)")
    click_chips(page, "conditions-grid", ["Migraine", "GERD / Acid reflux", "Eczema / Atopic dermatitis"])
    # Add a custom condition chip via the conditions-grid Add row
    page.fill('#custom-condition-input', "Lactose intolerance (mild)")
    page.locator('button[onclick="addCustomChip()"]').click()
    page.fill('input[name="health.exercise"]', "Trail run 3x/week, lifts twice, weekend hike")
    page.fill(
        'textarea[name="health.notes"]',
        "Manage migraines mostly through sleep + hydration. No prescription meds. "
        "Annual physical in March."
    )


def fill_hobbies(page):
    chips = [
        "Running", "Cycling", "Hiking", "Yoga",
        "Camping", "Stargazing / Astronomy",
        "Photography", "Woodworking",
        "Cooking", "Sourdough / Bread baking", "Coffee / Espresso",
        "Non-fiction reading", "Language learning",
        "Programming / Coding", "Home lab / Self-hosting",
        "Tabletop / Board games",
    ]
    for label in chips:
        loc = page.locator('#hobbies-grid .chip', has_text=label).first
        if loc.count() > 0:
            loc.click()
    # Add a custom hobby
    page.fill('#custom-hobby-input', "Bouldering")
    page.locator('#tab-hobbies .chip-add-row button').click()
    page.fill(
        'textarea[name="hobbies.other"]',
        "Slowly working on the Colorado 14ers — 18 down, 40-ish to go. "
        "Also restoring a 1970s teak dining table on weekends."
    )


def fill_identity(page):
    click_chips(page, "ideology-grid", ["Progressive", "Socially Liberal"])
    click_chips(page, "political-grid", ["Independent"])
    click_chips(page, "leaning-grid", ["Center-left"])
    click_chips(page, "sexuality-grid", ["Straight / Heterosexual"])
    click_chips(page, "gender-grid", ["Woman"])
    click_chips(page, "religion-grid", ["Spiritual but not religious"])
    click_chips(page, "causes-grid", [
        "Climate change action", "Renewable energy",
        "Mental health advocacy", "Affordable healthcare",
        "Digital privacy", "AI ethics / Safety",
    ])
    page.fill(
        'textarea[name="identity.notes"]',
        "Try to stay engaged but not consumed by politics. Care most about climate and "
        "healthcare access. Skeptical of strong partisan identification."
    )


def fill_goals(page):
    page.fill(
        'textarea[name="goals.current_projects"]',
        "Migrating the events pipeline from Kafka Connect to a custom Go ingestor. "
        "On the side: building a small recipe app for our family."
    )
    page.fill(
        'textarea[name="goals.short_term"]',
        "Ship pipeline migration to staging by July. Hit 20 14ers by end of season. "
        "Finish Spanish A2 course."
    )
    page.fill(
        'textarea[name="goals.long_term"]',
        "Buy a small mountain cabin near Nederland. Get to staff-principal level. "
        "Take a family sabbatical to Spain in 2028."
    )
    page.fill('input[name="goals.learning"]', "Go, Spanish, espresso latte art")


def fill_comms(page):
    page.select_option('select[name="comms.tone"]', label="Direct but warm")
    page.select_option('select[name="comms.length"]', label="Short unless depth is needed")
    page.select_option('select[name="comms.formatting"]', label="Prose over bullet points")
    page.select_option('select[name="comms.feedback"]', label="Tell me when I'm wrong, directly")
    click_chips(page, "humor-grid", ["Dry / deadpan", "Witty / wordplay"])
    click_chips(page, "vibes-grid", ["Curious", "Opinionated", "Pushback-friendly"])
    page.fill(
        'textarea[name="comms.never_do"]',
        "- Don't start with \"Great question!\" or any preamble\n"
        "- Don't add excessive caveats or disclaimers\n"
        "- Don't summarize my own message back to me\n"
        "- Don't pad responses with bullet points when a sentence would do"
    )
    page.fill(
        'textarea[name="comms.always_do"]',
        "- Push back when you disagree, with reasons\n"
        "- Ask one clarifying question before tackling a big task\n"
        "- Show the file path + line number when referencing code\n"
        "- Tell me when you're guessing vs. when you actually know"
    )
    page.select_option('select[name="comms.working_style"]', label="I come in with a clear plan")
    page.select_option('select[name="comms.when_stuck"]', label="Give me options and let me choose")
    page.fill(
        'textarea[name="comms.other"]',
        "I think best when I can write things out. Helps me to see two or three options "
        "with trade-offs spelled out, rather than a single 'best' recommendation."
    )


FILLERS = {
    "personal": fill_personal,
    "family": fill_family,
    "work": fill_work,
    "pets": fill_pets,
    "health": fill_health,
    "hobbies": fill_hobbies,
    "identity": fill_identity,
    "goals": fill_goals,
    "comms": fill_comms,
}


def main():
    tmpdir = tempfile.mkdtemp(prefix="claude-intake-screenshots-")
    app_path = Path(__file__).resolve().parent.parent / "app.py"
    flask_proc = subprocess.Popen(
        [sys.executable, str(app_path), "--memory-path", tmpdir],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        if not wait_for_server(URL):
            raise RuntimeError("Flask didn't start in time")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport=VIEWPORT, device_scale_factor=1)
            page = ctx.new_page()
            page.goto(URL, wait_until="networkidle")

            # Belt and suspenders: clear any hydrated state before filling.
            clear_form(page)

            # Fill every tab. We click the tab, then run its filler.
            for tab in TABS:
                page.click(f'button.tab-btn:has-text("{tab.capitalize()}")')
                page.wait_for_timeout(150)
                FILLERS[tab](page)

            # Now screenshot each tab.
            for i, tab in enumerate(TABS, start=1):
                page.click(f'button.tab-btn:has-text("{tab.capitalize()}")')
                page.wait_for_timeout(200)
                # Scroll to top
                page.evaluate("window.scrollTo(0, 0)")
                page.wait_for_timeout(100)
                out = OUT / f"{i:02d}-{tab}.png"
                page.screenshot(path=str(out), full_page=False)
                print(f"wrote {out}")

            # Full-page personal screenshot
            page.click('button.tab-btn:has-text("Personal")')
            page.wait_for_timeout(200)
            out_full = OUT / "00-personal-full.png"
            page.screenshot(path=str(out_full), full_page=True)
            print(f"wrote {out_full}")

            browser.close()
    finally:
        flask_proc.terminate()
        try:
            flask_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            flask_proc.kill()


if __name__ == "__main__":
    main()
