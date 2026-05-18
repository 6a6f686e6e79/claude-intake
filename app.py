from flask import Flask, render_template, request, jsonify
import json
import os
from pathlib import Path
from datetime import datetime

def fmt_month(value):
    """Convert '2024-02' to 'February 2024'."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%B %Y")
    except ValueError:
        # Try to salvage a mangled year (e.g. '20205-02' → '2025-02')
        try:
            parts = value.split("-")
            if len(parts) == 2:
                year = parts[0][:4]  # trim to 4 digits
                return datetime.strptime(f"{year}-{parts[1]}", "%Y-%m").strftime("%B %Y")
        except (ValueError, IndexError):
            pass
        return value

app = Flask(__name__)

CONFIG_FILE = Path("config.json")
DEFAULT_MEMORY_PATH = Path.home() / ".claude" / "memory"


def get_memory_path():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        return Path(cfg.get("memory_path", str(DEFAULT_MEMORY_PATH)))
    return DEFAULT_MEMORY_PATH


def update_memory_index(memory_path, slug, description, filename):
    memory_md = memory_path / "MEMORY.md"
    entry = f"- [{slug}]({filename}) — {description}"

    if memory_md.exists():
        lines = memory_md.read_text(encoding="utf-8").splitlines()
        new_lines, updated = [], False
        for line in lines:
            if line.startswith(f"- [{slug}]"):
                new_lines.append(entry)
                updated = True
            else:
                new_lines.append(line)
        if not updated:
            new_lines.append(entry)
        memory_md.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    else:
        memory_md.write_text(entry + "\n", encoding="utf-8")


def merge_content(existing_body, new_body):
    """Update existing key:value lines with new values; append keys not yet present."""
    if not new_body.strip():
        return existing_body.strip()

    result_lines = existing_body.strip().splitlines()

    for line in new_body.strip().splitlines():
        if not line.strip():
            continue
        if ": " in line:
            key = line.split(": ")[0].strip().lower()
            updated = False
            for j, rl in enumerate(result_lines):
                if rl.strip().lower().startswith(key + ":"):
                    result_lines[j] = line
                    updated = True
                    break
            if not updated:
                result_lines.append(line)
        else:
            if line.strip() not in [rl.strip() for rl in result_lines]:
                result_lines.append(line)

    return "\n".join(result_lines)


def write_memory_file(memory_path, slug, description, mem_type, content):
    memory_path.mkdir(parents=True, exist_ok=True)
    filename = f"{slug}.md"
    filepath = memory_path / filename

    if filepath.exists():
        raw = filepath.read_text(encoding="utf-8")
        # Split off frontmatter (--- ... ---)
        parts = raw.split("---", 2)
        existing_body = parts[2].strip() if len(parts) == 3 else raw.strip()
        merged_body = merge_content(existing_body, content)
        body = f"---\nname: {slug}\ndescription: {description}\nmetadata:\n  type: {mem_type}\n---\n\n{merged_body}\n"
    else:
        body = f"---\nname: {slug}\ndescription: {description}\nmetadata:\n  type: {mem_type}\n---\n\n{content}\n"

    filepath.write_text(body, encoding="utf-8")
    update_memory_index(memory_path, slug, description, filename)
    return str(filepath)


BOOTSTRAP_FILENAME = "claude-ai-bootstrap.md"
BOOTSTRAP_MAX_ENTRY_LEN = 500
BOOTSTRAP_MAX_ENTRIES = 25
BOOTSTRAP_TOPIC_TAGS = {
    "user-personal": "Personal",
    "user-family": "Family",
    "user-work": "Work",
    "user-pets": "Pets",
    "user-health": "Health",
    "user-hobbies": "Hobbies",
    "user-identity": "Identity",
    "user-goals": "Goals",
    "user-communication": "Communication",
}
BOOTSTRAP_HEADER = """# Claude.ai Memory Bootstrap

Before adding any entries, run `memory_user_edits view` to see existing memories. For each numbered entry below:
- If no existing memory covers the same topic, use `add`
- If an existing memory covers the same ground, use `replace` with the matching line number
- If an existing memory partially overlaps, merge the content and use `replace`

Stay under the 30-entry total limit. Flag any entries you skip or merge so the user knows what changed.

---

"""


def _topic_for(slug):
    if slug.startswith("user-notes-"):
        return "Notes"
    return BOOTSTRAP_TOPIC_TAGS.get(slug, slug.replace("user-", "").replace("-", " ").title())


def _split_body_into_chunks(body, budget):
    """Greedy split of body on '; ' boundaries, falling back to word splits.

    Each returned chunk is guaranteed ≤ budget chars. Splits prefer the
    higher-level semicolon boundary so related facts stay together when they
    can.
    """
    if len(body) <= budget:
        return [body]

    chunks = []
    current, current_len = [], 0
    for piece in body.split("; "):
        sep_len = 2 if current else 0
        if current and current_len + sep_len + len(piece) > budget:
            chunks.append("; ".join(current))
            current, current_len = [piece], len(piece)
        else:
            current.append(piece)
            current_len += sep_len + len(piece)
    if current:
        chunks.append("; ".join(current))

    final = []
    for chunk in chunks:
        if len(chunk) <= budget:
            final.append(chunk)
            continue
        sub, sub_len = [], 0
        for word in chunk.split():
            sep_len = 1 if sub else 0
            if sub and sub_len + sep_len + len(word) > budget:
                final.append(" ".join(sub))
                sub, sub_len = [word], len(word)
            else:
                sub.append(word)
                sub_len += sep_len + len(word)
        if sub:
            final.append(" ".join(sub))
    return final


def _memory_to_entries(memory):
    topic = _topic_for(memory["slug"])
    parts = [line.strip() for line in memory["content"].strip().splitlines() if line.strip()]
    body = "; ".join(parts)

    # Reserve worst-case prefix overhead "Topic (NN/NN): "
    budget = BOOTSTRAP_MAX_ENTRY_LEN - len(topic) - len(" (99/99): ")
    chunks = _split_body_into_chunks(body, budget)

    if len(chunks) == 1:
        # No numbering needed; re-check against tighter budget without suffix.
        single = f"{topic}: {chunks[0]}"
        if len(single) <= BOOTSTRAP_MAX_ENTRY_LEN:
            return [single]
    total = len(chunks)
    return [f"{topic} ({i + 1}/{total}): {c}" for i, c in enumerate(chunks)]


def build_bootstrap(memories):
    entries = []
    for mem in memories:
        for entry in _memory_to_entries(mem):
            if len(entries) >= BOOTSTRAP_MAX_ENTRIES:
                break
            entries.append(entry)
        if len(entries) >= BOOTSTRAP_MAX_ENTRIES:
            break
    if not entries:
        return ""
    numbered = "\n\n".join(f"{i + 1}. {e}" for i, e in enumerate(entries))
    return BOOTSTRAP_HEADER + numbered + "\n"


def write_bootstrap(memory_path, content):
    memory_path.mkdir(parents=True, exist_ok=True)
    filepath = memory_path / BOOTSTRAP_FILENAME
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def build_memories(data):
    memories = []

    # --- Personal ---
    p = data.get("personal", {})
    lines = []
    for label, key in [
        ("Name", "name"), ("Preferred name", "preferred_name"),
        ("Birthday", "birthday"), ("City", "city"),
        ("State/Province", "state"), ("Country", "country"), ("Timezone", "timezone"),
    ]:
        if p.get(key):
            lines.append(f"{label}: {p[key]}")
    if lines:
        memories.append({
            "slug": "user-personal",
            "description": "User's personal details: name, birthday, location",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Family ---
    f = data.get("family", {})
    lines = []
    if f.get("relationship_status"):
        lines.append(f"Relationship status: {f['relationship_status']}")
    if f.get("partner_name"):
        lines.append(f"Partner name: {f['partner_name']}")
    if f.get("partner_birthday"):
        lines.append(f"Partner birthday: {f['partner_birthday']}")
    for i, child in enumerate(f.get("children", []), 1):
        parts = [x for x in [child.get("name")] if x]
        if child.get("birthday"):
            parts.append(f"born {fmt_month(child['birthday'])}")
        if child.get("status"):
            parts.append(child["status"])
        if child.get("date_passed"):
            parts.append(f"passed away {fmt_month(child['date_passed'])}")
        if parts:
            lines.append(f"Child {i}: {', '.join(parts)}")
    if f.get("siblings"):
        lines.append(f"Siblings: {f['siblings']}")
    if f.get("parents"):
        lines.append(f"Parents: {f['parents']}")
    if f.get("other"):
        lines.append(f"Other family notes: {f['other']}")
    if lines:
        memories.append({
            "slug": "user-family",
            "description": "User's family: partner, children, parents, siblings",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Work ---
    w = data.get("work", {})
    lines = []
    for label, key in [
        ("Job title", "title"), ("Company", "company"), ("Industry", "industry"),
        ("Years of experience", "years_exp"), ("Work style", "work_style"),
    ]:
        if w.get(key):
            lines.append(f"{label}: {w[key]}")
    if w.get("notes"):
        lines.append(f"Work notes: {w['notes']}")
    if lines:
        memories.append({
            "slug": "user-work",
            "description": "User's professional background and work style",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Pets ---
    pets = data.get("pets", [])
    lines = []
    for i, pet in enumerate(pets, 1):
        parts = [x for x in [pet.get("name"), pet.get("species"), pet.get("breed")] if x]
        if pet.get("birthday"):
            parts.append(f"born {fmt_month(pet['birthday'])}")
        if pet.get("status"):
            parts.append(pet["status"])
        if pet.get("date_passed"):
            parts.append(f"passed away {fmt_month(pet['date_passed'])}")
        if parts:
            lines.append(f"Pet {i}: {', '.join(parts)}")
    if lines:
        memories.append({
            "slug": "user-pets",
            "description": "User's pets: names, species, breeds",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Health ---
    h = data.get("health", {})
    lines = []
    for label, key in [
        ("Dietary restrictions", "dietary"), ("Allergies", "allergies"),
        ("Health conditions", "conditions"), ("Exercise habits", "exercise"),
    ]:
        if h.get(key):
            lines.append(f"{label}: {h[key]}")
    if h.get("notes"):
        lines.append(f"Health notes: {h['notes']}")
    if lines:
        memories.append({
            "slug": "user-health",
            "description": "User's health, dietary restrictions, and wellness habits",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Hobbies ---
    ho = data.get("hobbies", {})
    lines = []
    if ho.get("interests"):
        lines.append(f"Interests & hobbies: {ho['interests']}")
    if ho.get("other"):
        lines.append(f"Additional notes: {ho['other']}")
    if lines:
        memories.append({
            "slug": "user-hobbies",
            "description": "User's hobbies, interests, and leisure activities",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Identity ---
    ident = data.get("identity", {})
    lines = []
    if ident.get("ideology"):
        lines.append(f"Political identity: {ident['ideology']}")
    if ident.get("political"):
        lines.append(f"Party / affiliation: {ident['political']}")
    if ident.get("leaning"):
        lines.append(f"Political leaning: {ident['leaning']}")
    if ident.get("sexuality"):
        lines.append(f"Sexuality / orientation: {ident['sexuality']}")
    if ident.get("gender"):
        lines.append(f"Gender identity: {ident['gender']}")
    if ident.get("religion"):
        lines.append(f"Religion / spirituality: {ident['religion']}")
    if ident.get("causes"):
        lines.append(f"Causes & issues: {ident['causes']}")
    if ident.get("notes"):
        lines.append(f"Identity notes: {ident['notes']}")
    if lines:
        memories.append({
            "slug": "user-identity",
            "description": "User's political views, sexuality, gender identity, religion, and causes",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Goals ---
    g = data.get("goals", {})
    lines = []
    if g.get("current_projects"):
        lines.append(f"Current projects: {g['current_projects']}")
    if g.get("short_term"):
        lines.append(f"Short-term goals: {g['short_term']}")
    if g.get("long_term"):
        lines.append(f"Long-term goals: {g['long_term']}")
    if g.get("learning"):
        lines.append(f"Currently learning: {g['learning']}")
    if lines:
        memories.append({
            "slug": "user-goals",
            "description": "User's current goals, projects, and things they're learning",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Communication Preferences ---
    c = data.get("comms", {})
    lines = []
    for label, key in [
        ("Tone preference", "tone"), ("Response length", "length"),
        ("Formatting preference", "formatting"), ("Feedback style", "feedback"),
        ("Working style", "working_style"), ("When stuck, wants Claude to", "when_stuck"),
    ]:
        if c.get(key):
            lines.append(f"{label}: {c[key]}")
    if c.get("never_do"):
        lines.append(f"\nNever do:\n{c['never_do']}")
    if c.get("always_do"):
        lines.append(f"\nAlways do:\n{c['always_do']}")
    if c.get("other"):
        lines.append(f"\nCollaboration notes:\n{c['other']}")
    if lines:
        memories.append({
            "slug": "user-communication",
            "description": "How the user wants Claude to communicate: tone, format, dos and don'ts",
            "type": "feedback",
            "content": "\n".join(lines),
        })

    # --- Free-form ---
    freeform = data.get("freeform", "").strip()
    if freeform:
        ts = datetime.now().strftime("%Y%m%d")
        memories.append({
            "slug": f"user-notes-{ts}",
            "description": "Free-form notes entered by user during intake",
            "type": "user",
            "content": freeform,
        })

    return memories


@app.route("/")
def index():
    return render_template("index.html", memory_path=str(get_memory_path()))


@app.route("/save-config", methods=["POST"])
def save_config():
    data = request.get_json()
    requested = data["memory_path"]
    resolved = Path(requested).expanduser().resolve()
    try:
        resolved.relative_to(Path.home())
    except ValueError:
        return jsonify({
            "success": False,
            "error": f"Memory path must be inside your home directory ({Path.home()}). Got: {resolved}",
        }), 400
    CONFIG_FILE.write_text(json.dumps({"memory_path": str(resolved)}, indent=2))
    return jsonify({"success": True, "memory_path": str(resolved)})


def _resolve_target(data):
    target = (data.get("target") or "claude-code").lower()
    if target not in ("claude-code", "claude-ai", "both"):
        target = "claude-code"
    return target


@app.route("/preview", methods=["POST"])
def preview():
    data = request.get_json()
    memories = build_memories(data)
    target = _resolve_target(data)
    bootstrap = build_bootstrap(memories) if target in ("claude-ai", "both") else None
    return jsonify({"memories": memories, "bootstrap": bootstrap, "target": target})


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json()
    memories = build_memories(data)
    memory_path = get_memory_path()
    target = _resolve_target(data)
    saved = []
    if target in ("claude-code", "both"):
        for mem in memories:
            path = write_memory_file(
                memory_path, mem["slug"], mem["description"], mem["type"], mem["content"]
            )
            saved.append({"slug": mem["slug"], "path": path})
    if target in ("claude-ai", "both"):
        bootstrap = build_bootstrap(memories)
        if bootstrap:
            path = write_bootstrap(memory_path, bootstrap)
            saved.append({"slug": "claude-ai-bootstrap", "path": path})
    return jsonify({"success": True, "saved": saved, "target": target})


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", host="127.0.0.1", port=5001)
