"""Smoke tests for tools/build_standalone.py.

Checks that the build produces a sane self-contained file and that the JS
port of build_memories / build_bootstrap stays byte-equivalent to the
Python implementation. node is required for the cross-check; if it's not
installed, those tests skip.

Run: pytest tests/test_standalone_build.py
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
STANDALONE = ROOT / "standalone.html"
BUILDER = ROOT / "tools" / "build_standalone.py"


@pytest.fixture(scope="module")
def built_html():
    subprocess.run([sys.executable, str(BUILDER)], check=True, cwd=str(ROOT))
    return STANDALONE.read_text(encoding="utf-8")


def test_no_jinja_remnants(built_html):
    assert "{{" not in built_html
    assert "{%" not in built_html


def test_css_inlined(built_html):
    assert "/static/style.css" not in built_html
    assert "<style>" in built_html
    assert "--accent: #6c47ff" in built_html  # marker from style.css


def test_settings_panel_stripped(built_html):
    assert 'id="settings-panel"' not in built_html
    assert 'class="settings-toggle"' not in built_html


def test_claude_ai_default(built_html):
    radio_block = re.search(
        r'<div class="target-toggle".*?</div>', built_html, re.DOTALL
    )
    assert radio_block, "target-toggle block not found"
    block = radio_block.group(0)
    # claude-ai radio must appear before claude-code and be the one with `checked`
    ai_pos = block.find('value="claude-ai"')
    code_pos = block.find('value="claude-code"')
    assert 0 <= ai_pos < code_pos
    assert re.search(r'value="claude-ai"\s+checked', block)


def test_generate_button_present(built_html):
    assert ">Generate</button>" in built_html
    # The old Flask-flavoured wording should be gone
    assert ">Save to Memory</button>" not in built_html


def test_js_syntactically_valid(built_html, tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    m = re.search(r"<script>\n(.*?)</script>", built_html, re.DOTALL)
    assert m, "inline <script> tag missing"
    js_file = tmp_path / "inline.js"
    js_file.write_text(m.group(1), encoding="utf-8")
    result = subprocess.run([node, "--check", str(js_file)],
                            capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"node --check failed:\n{result.stderr}"


SAMPLE = {
    "personal": {
        "name": "Riley Quinn", "preferred_name": "Riley",
        "birthday": "1988-04-15", "city": "Denver",
        "state": "CO", "country": "USA", "timezone": "Mountain (MT)",
    },
    "family": {
        "relationship_status": "Married", "partner_name": "Alex",
        "partner_birthday": "1987-09-02",
        "children": [{"name": "Emma", "birthday": "2018-02", "status": "Living"}],
        "siblings": "Sister Ava (29)", "parents": "Mom in Dallas",
    },
    "work": {
        "title": "PM", "company": "Acme", "years_exp": "8",
        "work_style": "Hybrid", "notes": "Side project",
        "prior_employers": [{"company": "OldCo", "title": "Eng", "years": "2015-2020"}],
    },
    "pets": [{"name": "Toby", "species": "Dog", "breed": "Golden Retriever",
              "birthday": "2020-03", "status": "Still with us"}],
    "health": {"dietary": "Vegetarian", "allergies": "Peanuts"},
    "hobbies": {"interests": "Running, Hiking"},
    "tech": {
        "os": "macOS, Linux", "os_details": "Arch on home rig",
        "shell": "zsh", "editor": "VS Code, Neovim", "phone": "iOS",
        "smart_home": "HomeKit / Apple Home", "gaming": "Steam Deck / Handheld",
        "notes": "Mostly remote, dotfiles in GitHub",
    },
    "identity": {"leaning": "Center-left", "religion": "Agnostic"},
    "goals": {"current_projects": "Launch MVP", "learning": "Spanish"},
    "comms": {
        "tone": "Direct but warm", "length": "Short unless depth is needed",
        "never_do": "Don't placate me", "always_do": "Push back when you disagree",
    },
    "freeform": "I think out loud.",
}


def test_schema_version_parity(built_html):
    """Python SCHEMA_VERSION (app.py) and JS SCHEMA_VERSION (template)
    must stay equal — they're the contract for backup-file compatibility.
    If you bump one, you must bump the other in the same commit."""
    from app import SCHEMA_VERSION as PY_VERSION
    m = re.search(r"const SCHEMA_VERSION = '([^']+)';", built_html)
    assert m, "SCHEMA_VERSION constant not found in built standalone JS"
    js_version = m.group(1)
    assert js_version == PY_VERSION, (
        f"SCHEMA_VERSION drift: app.py={PY_VERSION!r}, JS={js_version!r}. "
        "Bump both in the same commit."
    )


def test_js_port_matches_python(built_html, tmp_path):
    """Run buildMemories/buildBootstrap in node, compare to app.py output."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    from app import build_memories, build_bootstrap  # imported here so the
                                                     # test is skip-safe

    py_mems = build_memories(SAMPLE)
    py_boot = build_bootstrap(py_mems)
    py_boot_norm = re.sub(r"Generated: [^\n]+", "Generated: TS", py_boot)

    m = re.search(r"<script>\n(.*?)</script>", built_html, re.DOTALL)
    js_src = m.group(1)
    # Pull two non-contiguous chunks: BOOTSTRAP_TOPIC_TAGS (defined in the
    # template JS — also used by the import parser) and the override block's
    # build helpers. Stitching them avoids node trying to execute the rest of
    # the template JS, which touches the DOM and would crash at module load.
    tags = re.search(
        r"const BOOTSTRAP_TOPIC_TAGS = \{.*?\};",
        js_src, re.DOTALL,
    )
    helpers = re.search(
        r"const BOOTSTRAP_MAX_ENTRY_LEN.*?// ── YAML",
        js_src, re.DOTALL,
    )
    assert tags, "BOOTSTRAP_TOPIC_TAGS not found in template JS"
    assert helpers, "build helpers section not found in inline JS"

    runner_js = (
        tags.group(0) + "\n"
        + helpers.group(0)
        + "\nconst SAMPLE = " + json.dumps(SAMPLE) + ";\n"
        + "const mems = buildMemories(SAMPLE);\n"
        + "const boot = buildBootstrap(mems);\n"
        + "console.log(JSON.stringify({\n"
        + "  memories: mems,\n"
        + "  bootstrap: boot.replace(/Generated: [^\\n]+/, 'Generated: TS'),\n"
        + "}));\n"
    )
    js_file = tmp_path / "runner.js"
    js_file.write_text(runner_js, encoding="utf-8")
    result = subprocess.run([node, str(js_file)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"node run failed:\n{result.stderr}"

    js_out = json.loads(result.stdout)
    assert js_out["memories"] == py_mems, \
        "JS buildMemories diverged from Python build_memories"
    assert js_out["bootstrap"] == py_boot_norm, \
        "JS buildBootstrap diverged from Python build_bootstrap"


def test_js_import_parser_matches_python(built_html, tmp_path):
    """JS parseBootstrapFile should recover the same body text Python's
    _parse_bootstrap_file produces for every slug. user-pets is excluded
    because the JS port doesn't ingest pets in v1; family and work are
    included (the JS strips their row-format lines later in dataFromBootstrap,
    but parseBootstrapFile itself returns the raw body just like Python)."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    from app import build_memories, build_bootstrap, _parse_bootstrap_file

    py_boot = build_bootstrap(build_memories(SAMPLE))
    py_sections = _parse_bootstrap_file(py_boot)
    expected = {
        slug: body for slug, body in py_sections.items()
        if slug != "user-pets"
    }

    m = re.search(r"<script>\n(.*?)</script>", built_html, re.DOTALL)
    js_src = m.group(1)
    # The import parser lives in the template JS; pull the whole block from
    # BOOTSTRAP_TOPIC_TAGS through the end of dataFromBootstrap.
    parser_chunk = re.search(
        r"const BOOTSTRAP_TOPIC_TAGS = \{.*?function dataFromBootstrap[^\n]*\{.*?\n\}\n",
        js_src, re.DOTALL,
    )
    assert parser_chunk, "import parser chunk not found in template JS"

    runner_js = (
        parser_chunk.group(0)
        + "\nconst BOOT = " + json.dumps(py_boot) + ";\n"
        + "const parsed = parseBootstrapFile(BOOT);\n"
        + "console.log(JSON.stringify(parsed));\n"
    )
    js_file = tmp_path / "import_runner.js"
    js_file.write_text(runner_js, encoding="utf-8")
    result = subprocess.run([node, str(js_file)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, f"node run failed:\n{result.stderr}"
    js_sections = json.loads(result.stdout)

    for slug, body in expected.items():
        assert slug in js_sections, f"JS parser missed slug {slug!r}"
        assert js_sections[slug] == body, (
            f"body mismatch for {slug!r}\n"
            f"--- python ---\n{body}\n"
            f"--- js     ---\n{js_sections[slug]}"
        )


def test_js_dataFromBootstrap_extracts_family_work_kv(built_html, tmp_path):
    """dataFromBootstrap should pull flat fields out of user-family and user-work
    even when their bodies also contain row-format lines (Child N:, Prior
    employer N:, Military service:). The stripper removes the row lines so the
    continuation-line behavior of parseKvLines can't contaminate adjacent
    fields."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    from app import build_memories, build_bootstrap

    py_boot = build_bootstrap(build_memories(SAMPLE))

    m = re.search(r"<script>\n(.*?)</script>", built_html, re.DOTALL)
    js_src = m.group(1)
    parser_chunk = re.search(
        r"const BOOTSTRAP_TOPIC_TAGS = \{.*?function dataFromBootstrap[^\n]*\{.*?\n\}\n",
        js_src, re.DOTALL,
    )
    assert parser_chunk, "import parser chunk not found"

    runner_js = (
        parser_chunk.group(0)
        + "\nconst BOOT = " + json.dumps(py_boot) + ";\n"
        + "const out = dataFromBootstrap(BOOT);\n"
        + "console.log(JSON.stringify(out));\n"
    )
    js_file = tmp_path / "dfb_runner.js"
    js_file.write_text(runner_js, encoding="utf-8")
    result = subprocess.run([node, str(js_file)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)

    # Family: flat kv survives the strip; partner_birthday is NOT contaminated
    # by the trailing Child N: rows.
    fam = out["data"]["family"]
    assert fam["relationship_status"] == "Married"
    assert fam["partner_name"] == "Alex"
    assert fam["partner_birthday"] == "1987-09-02"
    assert fam["siblings"] == "Sister Ava (29)"
    assert fam["parents"] == "Mom in Dallas"

    # Work: flat kv plus Work notes survive; prior_employer rows don't pollute
    # adjacent fields.
    work = out["data"]["work"]
    assert work["title"] == "PM"
    assert work["company"] == "Acme"
    assert work["years_exp"] == "8"
    assert work["work_style"] == "Hybrid"
    assert work["notes"] == "Side project"

    # Family is restored, Pets is skipped.
    assert "Family" in out["restored"]
    assert "Work" in out["restored"]
    assert "Pets" in out["skipped"]


def test_js_tech_migration_shim_moves_pre_tech_chips(built_html, tmp_path):
    """Pre-Tech-tab bootstraps stored gaming platforms in hobbies.interests.
    After import, those values should move to tech.gaming so they land in the
    right tab on hydration."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")

    fake_boot = (
        "1. Hobbies: Interests & hobbies: Running, PC gaming, "
        "Hiking, Console gaming, Photography, VR gaming\n\n"
        "2. Tech: Computer OS: macOS\n"
    )

    m = re.search(r"<script>\n(.*?)</script>", built_html, re.DOTALL)
    js_src = m.group(1)
    parser_chunk = re.search(
        r"const BOOTSTRAP_TOPIC_TAGS = \{.*?function dataFromBootstrap[^\n]*\{.*?\n\}\n",
        js_src, re.DOTALL,
    )
    assert parser_chunk, "import parser chunk not found"

    runner_js = (
        parser_chunk.group(0)
        + "\nconst BOOT = " + json.dumps(fake_boot) + ";\n"
        + "const out = dataFromBootstrap(BOOT);\n"
        + "console.log(JSON.stringify(out.data));\n"
    )
    js_file = tmp_path / "shim_runner.js"
    js_file.write_text(runner_js, encoding="utf-8")
    result = subprocess.run([node, str(js_file)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)

    hobbies = [s.strip() for s in data["hobbies"]["interests"].split(",") if s.strip()]
    gaming = [s.strip() for s in (data["tech"].get("gaming") or "").split(",") if s.strip()]

    # Non-gaming hobbies stay put
    assert "Running" in hobbies
    assert "Hiking" in hobbies
    assert "Photography" in hobbies
    # Pre-Tech gaming entries left Hobbies entirely (case-insensitive match
    # on the source side, so lowercase variants migrate too)
    for src in ("PC gaming", "Console gaming", "VR gaming"):
        assert src not in hobbies, f"{src} should have left hobbies.interests"
    # And landed in tech.gaming, with "VR gaming" relabeled to the canonical
    # current chip name "VR / Headset gaming".
    assert "PC gaming" in gaming
    assert "Console gaming" in gaming
    assert "VR / Headset gaming" in gaming
    assert "VR gaming" not in gaming, "should be relabeled, not left as VR gaming"
    # Existing tech.os value isn't disturbed
    assert data["tech"]["os"] == "macOS"


def test_zip_encoder_roundtrips(built_html, tmp_path):
    """Build a zip in JS, write it to disk, unzip with the system unzip,
    confirm the contents survive."""
    node = shutil.which("node")
    unzip = shutil.which("unzip")
    if not node or not unzip:
        pytest.skip("node or unzip not installed")

    m = re.search(r"<script>\n(.*?)</script>", built_html, re.DOTALL)
    js_src = m.group(1)
    zip_section = re.search(
        r"const CRC32_TABLE.*?return out;\n\}", js_src, re.DOTALL,
    )
    assert zip_section, "ZIP encoder section not found"

    zip_path = tmp_path / "out.zip"
    payload = "Hello, world\nLine two\n"
    runner = (
        zip_section.group(0)
        + "\nconst fs = require('fs');\n"
        + f"const bytes = buildZip([{{name:'a.txt', content:{json.dumps(payload)}}}]);\n"
        + f"fs.writeFileSync({json.dumps(str(zip_path))}, Buffer.from(bytes));\n"
    )
    js_file = tmp_path / "ziprun.js"
    js_file.write_text(runner, encoding="utf-8")
    result = subprocess.run([node, str(js_file)], capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr

    out = subprocess.run([unzip, "-p", str(zip_path), "a.txt"],
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0
    assert out.stdout == payload
