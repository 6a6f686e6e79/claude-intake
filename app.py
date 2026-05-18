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
BOOTSTRAP_HEADER_TEMPLATE = """# Claude.ai Memory Bootstrap

Generated: {timestamp}

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
    header = BOOTSTRAP_HEADER_TEMPLATE.format(
        timestamp=datetime.now().isoformat(timespec="seconds")
    )
    numbered = "\n\n".join(f"{i + 1}. {e}" for i, e in enumerate(entries))
    return header + numbered + "\n"


def write_bootstrap(memory_path, content):
    memory_path.mkdir(parents=True, exist_ok=True)
    filepath = memory_path / BOOTSTRAP_FILENAME
    filepath.write_text(content, encoding="utf-8")
    return str(filepath)


def _nb(d, key):
    """Non-blank lookup: returns stripped string if non-empty, else ''.

    Treats whitespace-only values as blank so empty-but-truthy textarea
    fields don't produce dangling labels in the output.
    """
    val = d.get(key, "")
    if isinstance(val, str):
        return val.strip()
    return str(val) if val else ""


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
        v = _nb(p, key)
        if v:
            lines.append(f"{label}: {v}")
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
    for label, key in [
        ("Relationship status", "relationship_status"),
        ("Partner name", "partner_name"),
        ("Partner birthday", "partner_birthday"),
    ]:
        v = _nb(f, key)
        if v:
            lines.append(f"{label}: {v}")
    for i, child in enumerate(f.get("children", []), 1):
        parts = [x for x in [_nb(child, "name")] if x]
        if _nb(child, "birthday"):
            parts.append(f"born {fmt_month(_nb(child, 'birthday'))}")
        if _nb(child, "status"):
            parts.append(_nb(child, "status"))
        if _nb(child, "date_passed"):
            parts.append(f"passed away {fmt_month(_nb(child, 'date_passed'))}")
        if parts:
            lines.append(f"Child {i}: {', '.join(parts)}")
    for label, key in [
        ("Former partner / co-parent", "former_partner"),
        ("Siblings", "siblings"),
        ("Parents", "parents"),
        ("Other family notes", "other"),
    ]:
        v = _nb(f, key)
        if v:
            lines.append(f"{label}: {v}")
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
        v = _nb(w, key)
        if v:
            lines.append(f"{label}: {v}")
    if _nb(w, "notes"):
        lines.append(f"Work notes: {_nb(w, 'notes')}")
    for i, emp in enumerate(w.get("prior_employers", []), 1):
        parts = [x for x in [_nb(emp, "company"), _nb(emp, "title"), _nb(emp, "years")] if x]
        if _nb(emp, "notes"):
            parts.append(_nb(emp, "notes"))
        if parts:
            lines.append(f"Prior employer {i}: {', '.join(parts)}")
    mil_parts = []
    for label, key in [
        ("branch", "military_branch"), ("country", "military_country"),
        ("years served", "military_years"), ("field", "military_field"),
        ("rank", "military_rank"),
    ]:
        v = _nb(w, key)
        if v:
            mil_parts.append(f"{label} {v}")
    if mil_parts:
        lines.append(f"Military service: {', '.join(mil_parts)}")
    if _nb(w, "military_highlights"):
        lines.append(f"Military highlights: {_nb(w, 'military_highlights')}")
    if lines:
        memories.append({
            "slug": "user-work",
            "description": "User's professional background, prior employers, military service",
            "type": "user",
            "content": "\n".join(lines),
        })

    # --- Pets ---
    pets = data.get("pets", [])
    lines = []
    for i, pet in enumerate(pets, 1):
        parts = [x for x in [_nb(pet, "name"), _nb(pet, "species"), _nb(pet, "breed")] if x]
        if _nb(pet, "birthday"):
            parts.append(f"born {fmt_month(_nb(pet, 'birthday'))}")
        if _nb(pet, "status"):
            parts.append(_nb(pet, "status"))
        if _nb(pet, "date_passed"):
            parts.append(f"passed away {fmt_month(_nb(pet, 'date_passed'))}")
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
        v = _nb(h, key)
        if v:
            lines.append(f"{label}: {v}")
    if _nb(h, "notes"):
        lines.append(f"Health notes: {_nb(h, 'notes')}")
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
    if _nb(ho, "interests"):
        lines.append(f"Interests & hobbies: {_nb(ho, 'interests')}")
    if _nb(ho, "other"):
        lines.append(f"Additional notes: {_nb(ho, 'other')}")
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
    for label, key in [
        ("Political identity", "ideology"),
        ("Party / affiliation", "political"),
        ("Political leaning", "leaning"),
        ("Sexuality / orientation", "sexuality"),
        ("Gender identity", "gender"),
        ("Religion / spirituality", "religion"),
        ("Causes & issues", "causes"),
        ("Identity notes", "notes"),
    ]:
        v = _nb(ident, key)
        if v:
            lines.append(f"{label}: {v}")
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
    for label, key in [
        ("Current projects", "current_projects"),
        ("Short-term goals", "short_term"),
        ("Long-term goals", "long_term"),
        ("Currently learning", "learning"),
    ]:
        v = _nb(g, key)
        if v:
            lines.append(f"{label}: {v}")
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
        v = _nb(c, key)
        if v:
            lines.append(f"{label}: {v}")
    # Single-line label+content so the chunker can split on natural ;/newline
    # boundaries inside the user's text, not between the label and its body.
    for label, key in [
        ("Never do", "never_do"),
        ("Always do", "always_do"),
        ("Collaboration notes", "other"),
    ]:
        v = _nb(c, key)
        if v:
            lines.append(f"{label}: {v}")
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
