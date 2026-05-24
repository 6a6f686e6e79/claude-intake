# claude-intake

A local Flask web app for generating **Claude Code memory files**. Bootstrap your `~/.claude/memory/` directory and `MEMORY.md` index from a tabbed form instead of hand-writing YAML frontmatter.

![Personal tab](screenshots/00-personal-full.png)

## What it does

Claude Code reads memory files to personalize how it behaves across sessions: your name, your work, your family, how you prefer to communicate. Writing those files by hand means remembering the frontmatter schema, keeping the index in sync, and being disciplined about consistency over time.

claude-intake gives you a ten-tab form (Personal, Family, Work, Pets, Health, Hobbies, Tech, Identity, Goals, Communication), validates the input, writes properly-formatted memory files to `~/.claude/memory/`, and rebuilds the `MEMORY.md` index automatically. Edits merge instead of clobbering, so you can come back next week and add a hobby without losing yesterday's work.

Everything runs locally on `127.0.0.1`. Nothing is transmitted to the Anthropic API or anywhere else.

## Features

- Ten pre-built memory categories with curated fields for each
- YAML frontmatter generated automatically and consistently
- Re-entry safe: editing a category merges with the existing file rather than overwriting it
- `MEMORY.md` index file kept in sync on every save
- Configurable output path via the in-app Settings panel
- Pure local Flask app, no external API calls, no telemetry

## Quick start

```
git clone https://github.com/6a6f686e6e79/claude-intake.git
cd claude-intake
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5001>, fill in the tabs, click **Save to Memory**.

By default, files are written to `~/.claude/memory/`. Use the ⚙ Settings panel in the header to change the path.

## Standalone (no install)

For non-technical users who want to seed claude.ai memory without setting up Python, [`standalone.html`](standalone.html) is a single self-contained file that runs entirely in the browser. Two ways to use it:

- **Hosted via GitHub Pages (recommended):** [https://6a6f686e6e79.github.io/claude-intake/](https://6a6f686e6e79.github.io/claude-intake/) — opens directly to the form. The bare URL lands on `standalone.html` via an `index.html` redirect at the repo root.
- **Offline:** download `standalone.html`, double-click to open in any browser. Same form, works without internet.

Fill in the tabs, click **Generate** — a memory bootstrap is copied to your clipboard, ready to paste into a claude.ai conversation. Form data auto-saves to your browser's local storage as you type, so reloading the tab or closing it and coming back later doesn't lose your progress. For durable backups, use the **Backup / Restore** panel to download a JSON file you can keep wherever you keep important files.

**Why the Pages URL is preferred over `file://`**: browsers treat each `file://` path as its own origin, which makes `localStorage` behavior unreliable across sessions (and the clipboard API doesn't always work). The `https://` Pages origin gives you stable, predictable per-browser persistence and full clipboard support.

The standalone is generated from the same template as the Flask version, so the fields stay in sync. To regenerate after editing the template or CSS:

```
python3 tools/build_standalone.py
```

The Claude Code path is also supported as a secondary mode: pick the "Claude Code" target and **Generate** downloads a ZIP of `.md` files to extract into `~/.claude/memory/`.

### Enabling GitHub Pages (repo owner only)

To turn on the hosted Pages URL after a fresh clone or fork:

1. Settings → Pages
2. Source: **Deploy from a branch**
3. Branch: `master`, folder: `/ (root)`
4. Save. Pages takes a minute or two to provision.

The repo must be public (or you must have GitHub Pro for private Pages). Both `index.html` and `standalone.html` are committed at the repo root, so no build step is needed on GitHub's side — Pages just serves the files as-is.

## How Claude Code uses these files

When Claude Code starts in a project directory, it reads `CLAUDE.md` (project-level memory committed alongside the code) and, separately, files in `~/.claude/memory/` (user-level memory that follows you between projects). The combination gives Claude context about both the codebase and the person working in it.

claude-intake handles the user-level side: the persistent facts about you that should be available in every project, regardless of what you're working on. For project-level `CLAUDE.md` files, write those by hand alongside the code they describe.

For the underlying file format and lookup behavior, see the [Claude Code memory documentation](https://docs.claude.com/en/docs/claude-code/memory).

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

All screenshots use a fictional persona ("Riley Quinn"). No real personal data is shown.

## Regenerating screenshots

```
pip install playwright
playwright install chromium
python tools/take_screenshots.py
```

The script launches its own Flask instance against an empty temp memory dir so the fictional persona never mixes with your real data.

## Privacy

claude-intake has no backend, no analytics, no telemetry, and no network calls. The Flask version runs entirely on `127.0.0.1`; the standalone HTML runs entirely in your browser. Form data auto-saves to your browser's `localStorage`, which is scoped per-browser and per-device — clearing your browser data clears your form. The downloaded backup JSON is yours alone; the tool never sees it after you save it.

## Schema versioning (for contributors)

The standalone's **Backup / Restore** feature writes a JSON file with a top-level `schemaVersion` field. The version is defined in two places and they must stay equal:

- `SCHEMA_VERSION` in `app.py`
- `SCHEMA_VERSION` in `templates/index.html` (JS constant)

`tests/test_standalone_build.py::test_schema_version_parity` enforces equality on every build.

**Bump the version when:**

- A tab is added, renamed, or removed
- A field is added, renamed, or removed
- A field's value semantics change (e.g. CSV → list)

**To bump and add a migration:**

1. Update `SCHEMA_VERSION` in both files (same commit).
2. Add a transform to `MIGRATIONS` in both files, keyed `"<old>-to-<new>"`. The JS dict lives in `templates/index.html`; the Python dict in `app.py`. The transform takes the old data shape and returns the new one.
3. Existing backups created at the old version will run through the new transform on restore — no user action required.

The Python migration registry is kept symmetric with the JS one for consistency, even though only the standalone (browser-side) uses the backup-file format today.

## License

MIT. See [LICENSE](LICENSE).
