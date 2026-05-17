# claude-intake

A small local Flask app that helps you bootstrap your [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) memory files through a friendly web form instead of typing markdown frontmatter by hand.

Fill in as much (or as little) as you like across nine tabs — Personal, Family, Work, Pets, Health, Hobbies, Identity, Goals, Communication — and the app writes properly-formatted memory files into your `~/.claude/memory/` directory and keeps `MEMORY.md` up to date.

![Personal tab](screenshots/00-personal-full.png)

## Why

Claude Code reads memory files to personalize how it works with you. Writing those files by hand means remembering the frontmatter schema, the index file format, and being disciplined about consistency. This form does the typing for you and merges sensibly when you come back to update an entry.

Everything runs locally. Nothing is transmitted anywhere.

## Quick start

```bash
git clone https://github.com/6a6f686e6e79/claude-intake.git
cd claude-intake
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5001>, fill in the tabs, click **Save to Memory**.

By default, files are written to `~/.claude/memory/`. Use the ⚙ Settings panel in the header to change the path.

## Screenshots

| Tab | Preview |
| --- | --- |
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
