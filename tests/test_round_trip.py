"""Round-trip tests: build_memories → write → load → rebuild, assert content survives.

Run: pytest tests/
"""
import tempfile
from pathlib import Path
import pytest
from app import (
    build_memories, write_memory_file, load_memories,
    merge_content, build_bootstrap, _parse_bootstrap_file,
    fmt_month,
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
        for topic in ("Communication", "Personal", "Identity", "Work", "Pets"):
            assert topic in bt

    def test_parse_bootstrap_recovers_topics(self):
        mems = build_memories(SAMPLE)
        bt = build_bootstrap(mems)
        parsed = _parse_bootstrap_file(bt)
        assert "user-personal" in parsed
        assert "user-communication" in parsed
        assert "user-pets" in parsed

    def test_bootstrap_priority_communication_first(self):
        mems = build_memories(SAMPLE)
        bt = build_bootstrap(mems)
        comm_pos = bt.find("Communication:")
        personal_pos = bt.find("Personal:")
        assert comm_pos < personal_pos, "Communication should appear before Personal"


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
