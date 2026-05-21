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
    "identity": {"leaning": "Center-left", "religion": "Agnostic"},
    "goals": {"current_projects": "Launch MVP", "learning": "Spanish"},
    "comms": {
        "tone": "Direct but warm", "length": "Short unless depth is needed",
        "never_do": "Don't placate me", "always_do": "Push back when you disagree",
    },
    "freeform": "I think out loud.",
}


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
    # Extract just the chunk of standalone overrides we need; the surrounding
    # template JS touches the DOM which node can't run.
    needed = re.search(
        r"const BOOTSTRAP_MAX_ENTRY_LEN.*?// ── YAML",
        js_src, re.DOTALL,
    )
    assert needed, "build helpers section not found in inline JS"

    runner_js = (
        needed.group(0)
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
