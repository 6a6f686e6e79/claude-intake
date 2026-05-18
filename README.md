# claude-intake

A local Flask app for building and maintaining Claude memory files through a friendly web form instead of writing markdown frontmatter by hand.

Fill in as much (or as little) as you like across nine tabs — **Personal, Family, Work, Pets, Health, Hobbies, Identity, Goals, Communication** — then choose where to send it.

![Personal tab](screenshots/00-personal-full.png)

## Why

Claude reads memory files to personalize how it works with you. Writing those files by hand means remembering the frontmatter schema, the index format, and staying consistent across edits. This form does the typing, handles merging when you come back to update an entry, and outputs the right format for whichever Claude surface you're targeting.

Everything runs locally. Nothing is transmitted anywhere.

## Two output targets

| Target | What it writes | Use when |
|--------|---------------|----------|
| **Claude Code** | One `user-*.md` per section + `MEMORY.md` index in `~/.claude/memory/` | You use Claude Code (CLI or IDE extension) |
| **Claude.ai** | `claude-ai-bootstrap.md` — a numbered, prioritized list with step-by-step instructions for Claude | You use Claude.ai (or want to seed memories in any Claude session) |
| **Both** | Both of the above | You use both surfaces |

The output target toggle is in the form header. The bootstrap file is designed to be pasted into a Claude.ai conversation; Claude reads the instructions and populates your User Memories automatically, deduplicating against whatever is already there.

## Round-trip support

When you open the app, it reads your existing memory files back into the form. You see what's already saved, edit only what changed, and re-submit — the merge logic updates existing fields and appends new ones without ever deleting content you added by hand.

## Quick start

```bash
git clone https://github.com/6a6f686e6e79/claude-intake.git
cd claude-intake
python3 -m venv .venv && source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5001>, fill in the tabs, pick a target, click **Save to Memory**.

By default, files are written to `~/.claude/memory/`. Use the ⚙ Settings panel in the header to change the path.

## Tabs

| Tab | What it captures |
|-----|-----------------|
| Personal | Name, birthday, location, timezone, free-form notes |
| Family | Partner, children (with born/passed dates), parents, siblings |
| Work | Title, company, industry, work style, prior employers, military service |
| Pets | Name, species, breed (autocomplete), born/passed dates |
| Health | Dietary restrictions, allergies, conditions, exercise habits |
| Hobbies | Interests, leisure activities, additional notes |
| Identity | Political identity, party/affiliation, leaning, sexuality, gender, religion, causes |
| Goals | Current projects, short- and long-term goals, what you're learning |
| Communication | Tone, format, feedback style, humor, dos and don'ts for Claude |

## Merge behavior

Re-submitting with changed values updates existing fields. Fields you've hand-edited in the memory files but that don't appear in the form are preserved at the end of each file. To remove a value entirely, edit the memory file directly.

## Screenshots

| Tab | Preview |
|-----|---------|
| Personal | [01-personal.png](screenshots/01-personal.png) |
| Family | [02-family.png](screenshots/02-family.png) |
| Work | [03-work.png](screenshots/03-work.png) |
| Pets | [04-pets.png](screenshots/04-pets.png) |
| Health | [05-health.png](screenshots/05-health.png) |
| Hobbies | [06-hobbies.png](screenshots/06-hobbies.png) |
| Identity | [07-identity.png](screenshots/07-identity.png) |
| Goals | [08-goals.png](screenshots/08-goals.png) |
| Comms | [09-comms.png](screenshots/09-comms.png) |

All screenshots use a fictional persona ("Riley Quinn") — no real personal data.

## Regenerating screenshots

```bash
pip install playwright
playwright install chromium
python app.py &        # run the server in the background
python tools/take_screenshots.py
```

## License

MIT — see [LICENSE](LICENSE).
