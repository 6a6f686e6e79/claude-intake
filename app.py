from flask import Flask, render_template, request, jsonify
import json
import os
import re
from pathlib import Path
from datetime import datetime

def fmt_month(value):
    """Convert '2024-02' to 'February 2024'. Returns input unchanged on failure."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m").strftime("%B %Y")
    except ValueError:
        return value

# Bump when the form's data shape changes in a way that would break
# old backup files (tab added/renamed, field renamed, etc.). Mirrored
# in templates/index.html as SCHEMA_VERSION; the JS-port parity test
# enforces they stay equal.
SCHEMA_VERSION = "1"

# Migration registry. Keys are "fromVersion-to-toVersion"; values are
# pure (data) -> data transforms. Empty in v1; the pattern exists so
# future schema changes plug in without restructuring callers.
# Kept symmetric with the JS MIGRATIONS in templates/index.html.
MIGRATIONS = {}


def migrate_backup(data, from_version, to_version):
    if from_version == to_version:
        return data
    key = f"{from_version}-to-{to_version}"
    transform = MIGRATIONS.get(key)
    if transform is None:
        raise ValueError(
            f"No migration registered from {from_version} to {to_version}"
        )
    return transform(data)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024  # 1 MB

CONFIG_FILE = Path(__file__).resolve().parent / "config.json"
DEFAULT_MEMORY_PATH = Path.home() / ".claude" / "memory"


def get_memory_path():
    env_override = os.environ.get("CLAUDE_INTAKE_MEMORY_PATH")
    if env_override:
        return Path(env_override).expanduser()
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


LABEL_PATTERN = re.compile(r"^[A-Z][A-Za-z0-9 /&,()-]{0,60}: ")


def _chunk_body(body):
    """Group a body into chunks. Each chunk is (key_lower_or_None, lines).

    A chunk runs from one 'Label: ...' line through every following line
    (including blanks) up to (but not including) the next label line. Any
    lines before the first label form a single key=None orphan chunk.
    """
    chunks = []
    current_key = None
    current_lines = []
    for line in body.splitlines():
        if LABEL_PATTERN.match(line):
            if current_lines:
                chunks.append((current_key, current_lines))
            current_key = line.split(":", 1)[0].strip().lower()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        chunks.append((current_key, current_lines))
    return chunks


def merge_content(existing_body, new_body):
    """Merge new form content into existing file content.

    Operates on label chunks (a label line plus its continuation lines)
    rather than individual lines, so deleting part of a multi-line field
    in the form propagates: when a label is rewritten by the form, its
    old continuation lines are dropped along with the old label line.

    Preservation rules:
    - Orphan lines before the first labeled chunk are kept as-is.
    - Existing labels that aren't in the new content are kept (covers
      schema additions and hand-edited extras).
    - New content's ordering wins.
    """
    if not new_body.strip():
        return existing_body.strip()

    existing_chunks = _chunk_body(existing_body.strip())
    new_chunks = _chunk_body(new_body.strip())
    new_keys = {k for (k, _) in new_chunks if k is not None}

    result = []
    # Orphan prefix (anything before the first labeled chunk)
    for (k, lines) in existing_chunks:
        if k is None:
            result.append(lines)
        else:
            break

    # New content in its order — this is the form's view of the world
    for (_, lines) in new_chunks:
        result.append(lines)

    # Existing labels the form doesn't know about — preserve at the tail
    for (k, lines) in existing_chunks:
        if k is not None and k not in new_keys:
            result.append(lines)

    flat = []
    for chunk_lines in result:
        flat.extend(chunk_lines)
    return "\n".join(flat)


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
BOOTSTRAP_MAX_ENTRY_LEN = 500   # well under per-entry char caps on all known surfaces
BOOTSTRAP_MAX_ENTRIES = 25      # leaves headroom under claude.ai's 30-entry userMemories cap
BOOTSTRAP_TOPIC_TAGS = {
    "user-personal": "Personal",
    "user-family": "Family",
    "user-work": "Work",
    "user-pets": "Pets",
    "user-health": "Health",
    "user-hobbies": "Hobbies",
    "user-tech": "Tech",
    "user-identity": "Identity",
    "user-goals": "Goals",
    "user-communication": "Communication",
}
BOOTSTRAP_HEADER_TEMPLATE = """# Claude.ai Memory Bootstrap

Generated: {timestamp}

## Instructions — follow in order

**Step 1 — Check for existing memories first:**
If you have a `memory_user_edits` tool, **run `memory_user_edits view` first** — you need to see existing memories before adding, replacing, or merging. If you don't have that tool (Claude Code, API console, memory-disabled session), acknowledge that and proceed to Step 2 directly.

**Step 2 — Process each numbered entry below:**

If you have `memory_user_edits`, use it for each entry:
- If no existing memory covers the same topic → `add`
- If an existing memory covers the same ground → `replace` with the matching line number
- If an existing memory partially overlaps → merge the content and `replace`

If you don't have the tool, walk through each entry and restate the key facts in your own words. Don't compress the list into a bulleted summary — engage with each entry's content as if these are things you're being told about the user. On claude.ai, the conversation itself is the input to the automatic memory generator, so rich engagement produces richer memories.

**Priority note:** Entries are ordered by importance — communication preferences and core identity first, details last. If you are approaching the memory limit, skip from the bottom of the list, not the top.

**Step 3 — When all entries are processed:**

If you used the tool, summarize for the user: how many entries were added, how many replaced, how many skipped, and flag anything that was dropped or merged.

If you didn't, let the user know you've read through everything and that claude.ai will generate memories from this conversation automatically — typically within a day. Suggest they verify in a fresh chat by asking "what do you remember about me?"

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


BOOTSTRAP_PRIORITY = [
    "user-communication",
    "user-personal",
    "user-identity",
    "user-tech",
    "user-work",
    "user-family",
    "user-health",
    "user-hobbies",
    "user-goals",
    "user-pets",
]

def build_bootstrap(memories):
    mem_by_slug = {m["slug"]: m for m in memories}
    ordered = []
    for slug in BOOTSTRAP_PRIORITY:
        if slug in mem_by_slug:
            ordered.append(mem_by_slug.pop(slug))
    # Append anything not in the priority list (e.g. user-notes-*)
    ordered.extend(mem_by_slug.values())

    entries = []
    for mem in ordered:
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


SLUG_TO_SECTION = {
    "user-personal": "personal",
    "user-family": "family",
    "user-work": "work",
    "user-pets": "pets",
    "user-health": "health",
    "user-hobbies": "hobbies",
    "user-tech": "tech",
    "user-identity": "identity",
    "user-goals": "goals",
    "user-communication": "comms",
}

LABEL_TO_KEY = {
    "user-personal": {
        "Name": "name", "Preferred name": "preferred_name",
        "Birthday": "birthday", "City": "city",
        "State/Province": "state", "Country": "country", "Timezone": "timezone",
    },
    "user-family": {
        "Relationship status": "relationship_status",
        "Partner name": "partner_name", "Partner birthday": "partner_birthday",
        "Former partner / co-parent": "former_partner",
        "Siblings": "siblings", "Parents": "parents",
        "Other family notes": "other",
    },
    "user-work": {
        "Job title": "title", "Company": "company", "Industry": "industry",
        "Years of experience": "years_exp", "Work style": "work_style",
        "Work notes": "notes", "Military highlights": "military_highlights",
    },
    "user-health": {
        "Dietary restrictions": "dietary", "Allergies": "allergies",
        "Health conditions": "conditions", "Exercise habits": "exercise",
        "Health notes": "notes",
    },
    "user-hobbies": {
        "Interests & hobbies": "interests", "Additional notes": "other",
    },
    "user-tech": {
        "Computer OS": "os", "Distro / other OS details": "os_details",
        "Shell": "shell", "Code editor / IDE": "editor",
        "Phone OS": "phone", "Smart home ecosystem": "smart_home",
        "Gaming platforms": "gaming", "Tech notes": "notes",
    },
    "user-identity": {
        "Political identity": "ideology", "Party / affiliation": "political",
        "Political leaning": "leaning", "Sexuality / orientation": "sexuality",
        "Gender identity": "gender", "Religion / spirituality": "religion",
        "Causes & issues": "causes", "Identity notes": "notes",
    },
    "user-goals": {
        "Current projects": "current_projects", "Short-term goals": "short_term",
        "Long-term goals": "long_term", "Currently learning": "learning",
    },
    "user-communication": {
        "Tone preference": "tone", "Response length": "length",
        "Formatting preference": "formatting", "Feedback style": "feedback",
        "Humor style": "humor", "Personality vibes": "personality_vibes",
        "Working style": "working_style", "When stuck, wants Claude to": "when_stuck",
        "Never do": "never_do", "Always do": "always_do",
        "Collaboration notes": "other",
    },
}

MILITARY_LABEL_TO_KEY = {
    "branch ": "military_branch", "country ": "military_country",
    "years served ": "military_years", "field ": "military_field",
    "rank ": "military_rank",
}


def _strip_frontmatter(text):
    """Return the body of a memory file, dropping the leading --- ... --- block."""
    if not text.startswith("---"):
        return text
    end = text.find("\n---", 3)
    if end == -1:
        return text
    return text[end + 4:].lstrip("\n")


def _parse_month_back(s):
    """Inverse of fmt_month: 'February 2024' → '2024-02'. Returns input on failure."""
    try:
        return datetime.strptime(s.strip(), "%B %Y").strftime("%Y-%m")
    except ValueError:
        return s.strip()


def _parse_kv_lines(body, label_map):
    """Parse 'Label: value' lines into {key: value}, supporting multi-line values.

    Lines that don't start with a known label are treated as continuation of the
    previous label's value (joined with newlines). Lines before any recognized
    label are discarded.
    """
    result = {}
    current_key = None
    current_lines = []

    def flush():
        nonlocal current_key, current_lines
        if current_key is not None:
            result[current_key] = "\n".join(current_lines).strip()
        current_key = None
        current_lines = []

    for line in body.splitlines():
        stripped = line.rstrip()
        if not stripped.strip():
            if current_key is not None:
                current_lines.append("")
            continue
        matched = False
        for label, key in label_map.items():
            prefix = f"{label}: "
            bare = f"{label}:"
            if stripped.startswith(prefix) or stripped == bare:
                flush()
                current_key = key
                value = stripped[len(bare):].lstrip()
                current_lines = [value] if value else []
                matched = True
                break
        if not matched and current_key is not None:
            current_lines.append(stripped.strip())
    flush()
    return result


def _parse_child_line(rest):
    """Parse 'Emma, born February 2024, Living' → dict."""
    parts = [p.strip() for p in rest.split(",")]
    out = {}
    for p in parts:
        if p.startswith("born "):
            out["birthday"] = _parse_month_back(p[5:])
        elif p.startswith("passed away "):
            out["date_passed"] = _parse_month_back(p[12:])
        elif p in ("Living", "Passed away"):
            out["status"] = p
        elif "name" not in out:
            out["name"] = p
    return out


def _parse_pet_line(rest):
    """Parse 'Toby, Dog, Golden Retriever, born March 2020, Living' → dict."""
    parts = [p.strip() for p in rest.split(",")]
    out = {}
    positional = ["name", "species", "breed"]
    pos_idx = 0
    for p in parts:
        if p.startswith("born "):
            out["birthday"] = _parse_month_back(p[5:])
        elif p.startswith("passed away "):
            out["date_passed"] = _parse_month_back(p[12:])
        elif p in ("Still with us", "Passed away"):
            out["status"] = p
        elif pos_idx < len(positional):
            out[positional[pos_idx]] = p
            pos_idx += 1
    return out


def _parse_prior_employer_line(rest):
    parts = [p.strip() for p in rest.split(",")]
    keys = ["company", "title", "years", "notes"]
    return {keys[i]: p for i, p in enumerate(parts) if i < len(keys) and p}


def _parse_military_line(rest):
    out = {}
    for p in rest.split(","):
        p = p.strip()
        for label, key in MILITARY_LABEL_TO_KEY.items():
            if p.startswith(label):
                out[key] = p[len(label):].strip()
                break
    return out


def _parse_family(body):
    """Family section: kv pairs + 'Child N:' rows."""
    children = []
    non_child_lines = []
    for line in body.splitlines():
        m = re.match(r"^Child (\d+):\s*(.*)$", line.strip())
        if m:
            children.append(_parse_child_line(m.group(2)))
        else:
            non_child_lines.append(line)
    result = _parse_kv_lines("\n".join(non_child_lines), LABEL_TO_KEY["user-family"])
    result["children"] = children
    return result


def _parse_work(body):
    """Work section: kv pairs + 'Prior employer N:' + 'Military service:' rows."""
    employers = []
    military = {}
    other_lines = []
    for line in body.splitlines():
        stripped = line.strip()
        m = re.match(r"^Prior employer (\d+):\s*(.*)$", stripped)
        if m:
            employers.append(_parse_prior_employer_line(m.group(2)))
            continue
        if stripped.startswith("Military service: "):
            military = _parse_military_line(stripped[len("Military service: "):])
            continue
        other_lines.append(line)
    result = _parse_kv_lines("\n".join(other_lines), LABEL_TO_KEY["user-work"])
    result.update(military)
    result["prior_employers"] = employers
    return result


def _parse_pets(body):
    pets = []
    for line in body.splitlines():
        m = re.match(r"^Pet (\d+):\s*(.*)$", line.strip())
        if m:
            pets.append(_parse_pet_line(m.group(2)))
    return pets


SENTINEL_PATTERN = re.compile(
    r"^\s*###\s+(?:beginning|end)\s+of\s+form\s+###\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# Strip whole-line code-fence markers (opening and closing) so a paste
# wrapped in ```claude-intake-export ... ``` parses the same as a bare
# paste. Body content with embedded triple-backticks is a theoretical
# risk in the bootstrap format but doesn't occur in practice.
FENCE_PATTERN = re.compile(
    r"^\s*```(?:claude-intake-export)?\s*$",
    re.MULTILINE,
)


def _strip_sentinels(text):
    """Remove sentinel and fence-marker decoration.

    Sentinel: `### beginning of form ###` / `### end of form ###` lines,
    case-insensitive, whole-line, surrounding whitespace allowed.
    Fences: bare ``` and ```claude-intake-export marker lines.

    Lets the empty-form template, a partially-filled paste, a
    sentinel-wrapped paste, and a fenced export all share one wire
    format with optional decoration.
    """
    text = SENTINEL_PATTERN.sub("", text)
    text = FENCE_PATTERN.sub("", text)
    return text


def _parse_bootstrap_file(text):
    """Parse a claude-ai-bootstrap.md back into {slug: body_text}.

    Returns body text in the same format the per-file user-*.md bodies use,
    so it can be fed through the existing section parsers. Handles chunked
    entries (Communication (1/4), (2/4), ...) by concatenating their
    contents in document order with '; ' separators.

    Robust to whitespace-flattened paste: entries are located by matching
    on the topic-name vocabulary, not by newline boundaries. Also tolerant
    of `### beginning/end of form ###` sentinel decoration.
    """
    text = _strip_sentinels(text)
    # "Notes" is a parse-side alias for the top-level freeform textarea.
    # build_bootstrap emits user-notes-{date} slugs as "Notes: ..." entries
    # via _topic_for, so the parser has to recognize that topic name even
    # though it isn't in BOOTSTRAP_TOPIC_TAGS. Routes to the synthetic
    # "user-freeform" slug, which _populate_from_body lifts into data.freeform.
    topics = list(BOOTSTRAP_TOPIC_TAGS.values()) + ["Notes"]
    pattern = (
        r"\b\d+\.\s+(" + "|".join(re.escape(t) for t in topics) +
        r")(?:\s*\(\d+/\d+\))?\s*:\s*"
    )
    matches = list(re.finditer(pattern, text))
    if not matches:
        return {}

    by_topic = {}
    for i, m in enumerate(matches):
        topic = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        if content:
            by_topic.setdefault(topic, []).append(content)

    topic_to_slug = {v: k for k, v in BOOTSTRAP_TOPIC_TAGS.items()}
    topic_to_slug["Notes"] = "user-freeform"
    result = {}
    for topic, chunks in by_topic.items():
        slug = topic_to_slug.get(topic)
        if not slug:
            continue
        joined = "; ".join(chunks)
        # Reverse the bootstrap chunker's "; "-flatten back into per-line
        # "Label: value" entries that the section parsers expect. The split
        # is lossy on user-typed "; " — that's accepted; per-file backups in
        # load_memories are the source of truth for full-fidelity round-trip.
        lines = [p.strip() for p in joined.split("; ") if p.strip()]
        result[slug] = "\n".join(lines)
    return result


def _populate_from_body(data, slug, body):
    """Apply a parsed section body to the form-state dict in place."""
    if slug == "user-freeform":
        # Synthetic slug produced by _parse_bootstrap_file for "Notes:"
        # entries. Lifts the content into the top-level freeform textarea.
        if body:
            data["freeform"] = body
        return
    section = SLUG_TO_SECTION.get(slug)
    if not section or not body:
        return
    if slug == "user-family":
        data["family"] = _parse_family(body)
    elif slug == "user-work":
        data["work"] = _parse_work(body)
    elif slug == "user-pets":
        data["pets"] = _parse_pets(body)
    elif slug in LABEL_TO_KEY:
        data[section] = _parse_kv_lines(body, LABEL_TO_KEY[slug])


def load_memories(memory_path):
    """Parse user-*.md files in memory_path back into the form's data shape.

    Inverse of build_memories. Returns a dict matching the JSON the /submit
    route consumes, so build_memories(load_memories(path)) round-trips.
    """
    data = {
        "personal": {}, "family": {"children": []},
        "work": {"prior_employers": []}, "pets": [],
        "health": {}, "hobbies": {}, "tech": {}, "identity": {},
        "goals": {}, "comms": {}, "freeform": "",
    }
    if not memory_path.exists():
        return data

    def _read_body(slug):
        path = memory_path / f"{slug}.md"
        if not path.exists():
            return None
        try:
            return _strip_frontmatter(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as e:
            app.logger.warning("Skipping %s: %s", path, e)
            return None

    loaded_from_file = set()
    for slug in ("user-personal", "user-family", "user-work", "user-pets",
                 "user-health", "user-hobbies", "user-tech", "user-identity",
                 "user-goals", "user-communication"):
        body = _read_body(slug)
        if body is None:
            continue
        _populate_from_body(data, slug, body)
        loaded_from_file.add(slug)

    # Backfill any section that doesn't have a per-file backup from the
    # claude-ai-bootstrap.md (if present). Per-file backups always win —
    # they're lossless, the bootstrap flattens multi-line values.
    bootstrap_path = memory_path / BOOTSTRAP_FILENAME
    if bootstrap_path.exists():
        try:
            text = bootstrap_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            app.logger.warning("Could not read %s: %s", bootstrap_path, e)
            text = ""
        if text:
            for slug, body in _parse_bootstrap_file(text).items():
                if slug in loaded_from_file:
                    continue
                _populate_from_body(data, slug, body)

    return data


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

    # --- Tech ---
    t = data.get("tech", {})
    lines = []
    for label, key in [
        ("Computer OS", "os"),
        ("Distro / other OS details", "os_details"),
        ("Shell", "shell"),
        ("Code editor / IDE", "editor"),
        ("Phone OS", "phone"),
        ("Smart home ecosystem", "smart_home"),
        ("Gaming platforms", "gaming"),
        ("Tech notes", "notes"),
    ]:
        v = _nb(t, key)
        if v:
            lines.append(f"{label}: {v}")
    if lines:
        memories.append({
            "slug": "user-tech",
            "description": "User's tech stack: OS, shell, editor, phone, smart home, gaming platforms",
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
        ("Humor style", "humor"), ("Personality vibes", "personality_vibes"),
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
    memory_path = get_memory_path()
    initial_data = load_memories(memory_path)
    return render_template(
        "index.html",
        memory_path=str(memory_path),
        initial_data=initial_data,
    )


@app.route("/save-config", methods=["POST"])
def save_config():
    data = request.get_json(silent=True) or {}
    requested = data.get("memory_path")
    if not requested or not isinstance(requested, str):
        return jsonify({
            "success": False,
            "error": "memory_path is required and must be a string",
        }), 400
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
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-path", help="Override memory path (skips config.json)")
    args = parser.parse_args()
    if args.memory_path:
        os.environ["CLAUDE_INTAKE_MEMORY_PATH"] = args.memory_path
    app.run(debug=os.getenv("FLASK_DEBUG") == "1", host="127.0.0.1", port=5001)
