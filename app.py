from flask import Flask, render_template, request, jsonify
import json
from pathlib import Path
from datetime import datetime

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


def write_memory_file(memory_path, slug, description, mem_type, content):
    memory_path.mkdir(parents=True, exist_ok=True)
    filename = f"{slug}.md"
    filepath = memory_path / filename
    body = f"---\nname: {slug}\ndescription: {description}\nmetadata:\n  type: {mem_type}\n---\n\n{content}\n"
    filepath.write_text(body, encoding="utf-8")
    update_memory_index(memory_path, slug, description, filename)
    return str(filepath)


def build_memories(data):
    memories = []

    # --- Personal ---
    p = data.get("personal", {})
    lines = []
    for label, key in [
        ("Name", "name"), ("Birthday", "birthday"), ("City", "city"),
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
        parts = [x for x in [child.get("name"), child.get("birthday")] if x]
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
        parts = [x for x in [pet.get("name"), pet.get("species"), pet.get("breed"), pet.get("age")] if x]
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
        lines.append(f"Interests: {ho['interests']}")
    if ho.get("sports"):
        lines.append(f"Sports/fitness: {ho['sports']}")
    if ho.get("creative"):
        lines.append(f"Creative pursuits: {ho['creative']}")
    if ho.get("tech"):
        lines.append(f"Tech/gaming: {ho['tech']}")
    if ho.get("other"):
        lines.append(f"Other hobbies: {ho['other']}")
    if lines:
        memories.append({
            "slug": "user-hobbies",
            "description": "User's hobbies, interests, and leisure activities",
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
    CONFIG_FILE.write_text(json.dumps({"memory_path": data["memory_path"]}, indent=2))
    return jsonify({"success": True, "memory_path": data["memory_path"]})


@app.route("/preview", methods=["POST"])
def preview():
    data = request.get_json()
    memories = build_memories(data)
    return jsonify({"memories": memories})


@app.route("/submit", methods=["POST"])
def submit():
    data = request.get_json()
    memories = build_memories(data)
    memory_path = get_memory_path()
    saved = []
    for mem in memories:
        path = write_memory_file(
            memory_path, mem["slug"], mem["description"], mem["type"], mem["content"]
        )
        saved.append({"slug": mem["slug"], "path": path})
    return jsonify({"success": True, "saved": saved})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
