"""Round-trip tests: build_memories → write → load → rebuild, assert content survives.

Run: pytest tests/
"""
import tempfile
from pathlib import Path
import pytest
from app import (
    build_memories, write_memory_file, load_memories,
    merge_content, build_bootstrap, _parse_bootstrap_file,
    fmt_month, _chunk_body, LABEL_PATTERN, LABEL_TO_KEY,
)

SAMPLE = {
    "personal": {
        "name": "Riley Quinn", "preferred_name": "Riley",
        "birthday": "1989-07-14", "city": "Boulder",
        "state": "CO", "country": "USA", "timezone": "America/Denver",
    },
    "family": {
        "relationship_status": "Married",
        "partner_name": "Morgan Hale", "partner_birthday": "1990-03-22",
        "former_partner": "", "siblings": "Felix (36), Nora (31)",
        "parents": "Ellen and Roger in Madison WI", "other": "",
        "children": [
            {"name": "Sienna", "birthday": "2017-05", "status": "Living", "date_passed": ""},
            {"name": "Wren", "birthday": "2020-11", "status": "Living", "date_passed": ""},
        ],
    },
    "work": {
        "title": "Staff Data Engineer", "company": "Northwind Logistics",
        "industry": "Supply chain / SaaS", "years_exp": "11",
        "work_style": "Remote", "notes": "Lead the warehouse-events pipeline team",
        "prior_employers": [
            {"company": "Acme Corp", "title": "Data Engineer", "years": "2015–2019", "notes": ""},
        ],
        "military_branch": "", "military_country": "", "military_years": "",
        "military_field": "", "military_rank": "", "military_highlights": "",
    },
    "pets": [
        {"name": "Maple", "species": "Dog", "breed": "Australian Shepherd",
         "birthday": "2021-04", "status": "Still with us", "date_passed": ""},
        {"name": "Pickle", "species": "Cat", "breed": "Domestic Shorthair",
         "birthday": "2019-09", "status": "Still with us", "date_passed": ""},
    ],
    "health": {
        "dietary": "Mostly vegetarian", "allergies": "Tree nuts",
        "conditions": "Migraine, GERD", "exercise": "Trail run 3x/week",
        "notes": "Manage migraines through sleep",
    },
    "hobbies": {
        "interests": "Running, Hiking, Photography",
        "other": "Working on the Colorado 14ers",
    },
    "tech": {
        "os": "macOS, Linux",
        "os_details": "Arch on the home rig",
        "shell": "zsh, fish",
        "editor": "VS Code, Neovim",
        "phone": "iOS",
        "smart_home": "HomeKit / Apple Home, Home Assistant",
        "gaming": "PlayStation, Steam Deck / Handheld",
        "notes": "Daily-driver MBP for work, custom Linux box at home",
    },
    "identity": {
        "ideology": "Progressive", "political": "Independent",
        "leaning": "Center-left", "sexuality": "Straight / Heterosexual",
        "gender": "Woman", "religion": "Spiritual but not religious",
        "causes": "Climate change action, Digital privacy",
        "notes": "Care most about climate and healthcare",
    },
    "goals": {
        "current_projects": "Pipeline migration to Go",
        "short_term": "Ship migration to staging by July",
        "long_term": "Buy a mountain cabin",
        "learning": "Go, Spanish",
    },
    "comms": {
        "tone": "Direct but warm", "length": "Short unless depth is needed",
        "formatting": "Prose over bullet points",
        "feedback": "Tell me when I'm wrong, directly",
        "humor": "Dry / deadpan, Witty / wordplay",
        "personality_vibes": "Curious, Opinionated",
        "working_style": "I come in with a clear plan",
        "when_stuck": "Give me options and let me choose",
        "never_do": "Don't start with Great question!",
        "always_do": "Push back when you disagree",
        "other": "I think best when I can write things out",
    },
    "freeform": "",
}


def _write_all(data, path):
    for mem in build_memories(data):
        write_memory_file(path, mem["slug"], mem["description"], mem["type"], mem["content"])


# --- merge_content ---

class TestMergeContent:
    def test_updates_existing_key(self):
        existing = "Name: Old Name\nCity: Denver"
        new = "Name: New Name\nCity: Denver"
        result = merge_content(existing, new)
        assert "Name: New Name" in result
        assert "Name: Old Name" not in result

    def test_appends_new_key(self):
        existing = "Name: Riley"
        new = "Name: Riley\nCity: Boulder"
        result = merge_content(existing, new)
        assert "City: Boulder" in result

    def test_preserves_hand_edited_extras(self):
        existing = "Name: Riley\nSecret: hand-edited"
        new = "Name: Riley Quinn"
        result = merge_content(existing, new)
        assert "Secret: hand-edited" in result
        assert "Name: Riley Quinn" in result

    def test_empty_new_body_returns_existing(self):
        existing = "Name: Riley"
        assert merge_content(existing, "") == existing.strip()

    def test_multiline_value_replaced(self):
        existing = "Notes: old note\n  continuation"
        new = "Notes: new note"
        result = merge_content(existing, new)
        assert "new note" in result
        assert "old note" not in result
        assert "continuation" not in result


# --- section round-trips ---

class TestRoundTrip:
    def test_personal(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        p = loaded["personal"]
        assert p["name"] == "Riley Quinn"
        assert p["preferred_name"] == "Riley"
        assert p["city"] == "Boulder"
        assert p["state"] == "CO"
        assert p["timezone"] == "America/Denver"

    def test_family_with_children(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        f = loaded["family"]
        assert f["relationship_status"] == "Married"
        assert f["partner_name"] == "Morgan Hale"
        children = f["children"]
        assert len(children) == 2
        assert children[0]["name"] == "Sienna"
        assert children[0]["birthday"] == "2017-05"
        assert children[1]["name"] == "Wren"

    def test_work_with_prior_employer(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        w = loaded["work"]
        assert w["title"] == "Staff Data Engineer"
        assert w["company"] == "Northwind Logistics"
        employers = w["prior_employers"]
        assert len(employers) == 1
        assert employers[0]["company"] == "Acme Corp"

    def test_pets_with_breed_and_dates(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        pets = loaded["pets"]
        assert len(pets) == 2
        assert pets[0]["name"] == "Maple"
        assert pets[0]["species"] == "Dog"
        assert pets[0]["breed"] == "Australian Shepherd"
        assert pets[0]["birthday"] == "2021-04"
        assert pets[1]["name"] == "Pickle"

    def test_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        i = loaded["identity"]
        assert i["ideology"] == "Progressive"
        assert i["sexuality"] == "Straight / Heterosexual"
        assert i["causes"] == "Climate change action, Digital privacy"

    def test_tech(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        t = loaded["tech"]
        assert t["os"] == "macOS, Linux"
        assert t["os_details"] == "Arch on the home rig"
        assert t["shell"] == "zsh, fish"
        assert t["editor"] == "VS Code, Neovim"
        assert t["phone"] == "iOS"
        assert t["smart_home"] == "HomeKit / Apple Home, Home Assistant"
        assert t["gaming"] == "PlayStation, Steam Deck / Handheld"
        assert t["notes"] == "Daily-driver MBP for work, custom Linux box at home"

    def test_comms_with_humor_and_vibes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        c = loaded["comms"]
        assert c["tone"] == "Direct but warm"
        assert c["humor"] == "Dry / deadpan, Witty / wordplay"
        assert c["personality_vibes"] == "Curious, Opinionated"
        assert c["never_do"] == "Don't start with Great question!"

    def test_full_content_match(self):
        """build → write → load → rebuild produces the same memory content."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)
            original_mems = build_memories(SAMPLE)
            _write_all(SAMPLE, path)
            loaded = load_memories(path)
        rebuilt_mems = build_memories(loaded)

        original = {m["slug"]: m["content"] for m in original_mems if not m["slug"].startswith("user-notes-")}
        rebuilt = {m["slug"]: m["content"] for m in rebuilt_mems}

        for slug, content in original.items():
            assert slug in rebuilt, f"slug {slug!r} lost on round-trip"
            assert content == rebuilt[slug], (
                f"content mismatch for {slug!r}\n"
                f"--- original ---\n{content}\n"
                f"--- rebuilt  ---\n{rebuilt[slug]}"
            )


# --- bootstrap round-trip ---

class TestBootstrap:
    def test_bootstrap_contains_all_topics(self):
        mems = build_memories(SAMPLE)
        bt = build_bootstrap(mems)
        for topic in ("Communication", "Personal", "Identity", "Tech", "Work", "Pets"):
            assert topic in bt

    def test_parse_bootstrap_recovers_topics(self):
        mems = build_memories(SAMPLE)
        bt = build_bootstrap(mems)
        parsed = _parse_bootstrap_file(bt)
        assert "user-personal" in parsed
        assert "user-communication" in parsed
        assert "user-pets" in parsed
        assert "user-tech" in parsed

    def test_bootstrap_priority_communication_first(self):
        mems = build_memories(SAMPLE)
        bt = build_bootstrap(mems)
        comm_pos = bt.find("Communication:")
        personal_pos = bt.find("Personal:")
        assert comm_pos < personal_pos, "Communication should appear before Personal"

    def test_bootstrap_roundtrip_preserves_semicolon_content(self):
        """Content survives; verbatim "; " separators do not.

        The bootstrap is a lossy snapshot by design (priority-ordered,
        character-capped, chunked). Per-file memory files are the source of
        truth for round-trip fidelity (see load_memories).
        """
        sample = dict(SAMPLE)
        sample["comms"] = dict(sample["comms"])
        sample["comms"]["other"] = "Item one; item two; with nested clauses"
        mems = build_memories(sample)
        bt = build_bootstrap(mems)
        parsed = _parse_bootstrap_file(bt)
        body = parsed["user-communication"]
        assert "Item one" in body
        assert "item two" in body
        assert "with nested clauses" in body
        # No escape artifacts in the user-visible bootstrap
        assert r"\;" not in bt

    def test_parser_routes_notes_topic_to_freeform(self):
        """build_bootstrap emits user-notes-{date} slugs as 'Notes:' entries.
        The parser must recognize 'Notes' as a topic name and route its
        content to the synthetic 'user-freeform' slug so _populate_from_body
        can lift it into the top-level data.freeform field."""
        from app import _populate_from_body
        text = (
            "1. Personal: Name: Riley Quinn\n"
            "2. Notes: Some overflow content the schema doesn't have a slot for."
        )
        sections = _parse_bootstrap_file(text)
        assert "user-freeform" in sections, "Notes topic not routed to user-freeform"
        assert "Some overflow content" in sections["user-freeform"]

        data = {"freeform": ""}
        _populate_from_body(data, "user-freeform", sections["user-freeform"])
        assert "Some overflow content" in data["freeform"]

    def test_freeform_round_trips_through_bootstrap(self):
        """A non-empty freeform value survives build_bootstrap → parse →
        _populate_from_body and lands back in data.freeform."""
        from app import _populate_from_body
        sample = dict(SAMPLE)
        sample["freeform"] = "Some long-form context that doesn't fit elsewhere."
        mems = build_memories(sample)
        bt = build_bootstrap(mems)
        sections = _parse_bootstrap_file(bt)
        assert "user-freeform" in sections
        data = {"freeform": ""}
        _populate_from_body(data, "user-freeform", sections["user-freeform"])
        assert "Some long-form context" in data["freeform"]

    def test_parser_handles_bare_sentinel_and_fenced_input(self):
        """Same payload, three wrappings: bare, sentinel-wrapped, fenced.
        All three should produce identical parsed output. Locks in the
        format-as-protocol promise — the empty-form template, a partial
        paste, and a fenced export are all the same input shape."""
        bare = (
            "1. Personal: Name: Riley Quinn; City: Boulder\n"
            "2. Tech: Computer OS: macOS; Shell: zsh"
        )
        wrapped = "### beginning of form ###\n" + bare + "\n### end of form ###"
        # Mix case + extra whitespace to exercise the case-insensitive /
        # whitespace-tolerant matching.
        wrapped_varied = (
            "  ### Beginning Of Form ###\n" + bare + "\n###  END OF FORM  ###  "
        )
        fenced = "```claude-intake-export\n" + bare + "\n```"

        baseline = _parse_bootstrap_file(bare)
        assert _parse_bootstrap_file(wrapped) == baseline
        assert _parse_bootstrap_file(wrapped_varied) == baseline
        assert _parse_bootstrap_file(fenced) == baseline

    def test_bootstrap_prompt_handles_no_tool_case(self):
        """Step 2 and Step 3 must address sessions without memory_user_edits.

        Without explicit no-tool branches, Claude on claude.ai defaults to
        a bulleted summary, which is then summarized again by the automatic
        memory generator — double-compression loses detail at ingestion.
        """
        bt = build_bootstrap(build_memories(SAMPLE))
        # Split on the bolded section headers, not bare "Step 2" — the latter
        # also appears in Step 1's body ("proceed to Step 2 directly").
        step_2 = bt.split("**Step 2 —")[1].split("**Step 3 —")[0]
        step_3 = bt.split("**Step 3 —")[1].split("---")[0]

        # Step 2 has a tool branch and a no-tool branch
        assert "memory_user_edits" in step_2
        assert "If you don't have the tool" in step_2 or "Without" in step_2

        # Step 3 has a tool branch and a no-tool branch
        assert "added" in step_3.lower()  # tool branch (counts)
        assert ("automatically" in step_3.lower()
                or "what do you remember" in step_3.lower())  # no-tool branch


# --- fmt_month ---

class TestFmtMonth:
    def test_valid(self):
        assert fmt_month("2024-02") == "February 2024"

    def test_empty(self):
        assert fmt_month("") == ""

    def test_mangled_year_returns_input(self):
        assert fmt_month("20205-02") == "20205-02"
        assert fmt_month("02025-02") == "02025-02"
        assert fmt_month("99-02") == "99-02"
        assert fmt_month("not-a-date") == "not-a-date"


# --- _chunk_body label pattern ---

class TestChunkBody:
    def test_ignores_lowercase_label_lookalikes(self):
        # Lowercase sentence with ": " inside a multi-line value should not
        # split the chunk under the old loose check it would have.
        body = (
            "Notes: line one\n"
            "url: example.com\n"
            "lots of context: this is just prose\n"
            "more notes"
        )
        chunks = _chunk_body(body)
        assert len(chunks) == 1
        assert chunks[0][0] == "notes"
        assert len(chunks[0][1]) == 4

    def test_label_pattern_matches_all_real_labels(self):
        for section_labels in LABEL_TO_KEY.values():
            for label in section_labels:
                assert LABEL_PATTERN.match(f"{label}: value"), f"pattern missed: {label!r}"

    def test_label_pattern_matches_every_emitted_label(self):
        """build_memories emits dynamic labels (Child N, Pet N, Prior employer
        N, Military service) that aren't enumerated in LABEL_TO_KEY. Lock in
        that LABEL_PATTERN matches them so _chunk_body keeps treating them as
        labels rather than continuation lines."""
        mems = build_memories(SAMPLE)
        for m in mems:
            for line in m["content"].splitlines():
                if ": " in line:
                    assert LABEL_PATTERN.match(line), (
                        f"emitted by {m['slug']!r} but pattern missed it: {line!r}"
                    )
