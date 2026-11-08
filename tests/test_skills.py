"""Skills, as Claude has them: folders with a SKILL.md, listed in her prompt, loaded with skill_use when a task
matches, started by the user with /name, and written by her with the file tools."""

import json

import pytest
from conftest import turn

from sentientmilk_framework import BrainError
from sentientmilk_framework.brain import validate_items
from sentientmilk_framework.skills import Skills, frontmatter, render
from sentientmilk_framework.testing import tool_call

GREETING = """---
name: greeting-guests
description: "Greets guests by name: warmly. Use when someone arrives."
argument-hint: "[name]"
metadata:
  version: 2
allowed-tools:
- files_read
---
# Greeting guests

Say hello to $0 and offer tea. Notes: ${SKILL_DIR}/notes.md. Tea costs \\$2.
"""
DEPLOYING = """---
name: deploying
description: Deploys the site. Use when the user says deploy.
disable-model-invocation: true
---
Run the deploy script, then report: $ARGUMENTS
"""


def write(home, name, text, **files):
    folder = home / "skills" / name
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "SKILL.md").write_text(text, encoding="utf-8")
    for file, content in files.items():
        (folder / file).write_text(content, encoding="utf-8")
    return folder


def allow(event):
    return "allow"


def system(payload):
    return payload["messages"][0]["content"]


def results(payload):
    return {m["tool_call_id"]: m["content"] for m in payload["messages"] if m["role"] == "tool"}


@pytest.fixture
def skilled(brain):
    brain.client.declare_app("sk", name="Sk", environment="A test.", toolkits=["files", "skills"])
    brain.client.update_session("sk", "main", cwd=str(brain.work), roots=[str(brain.work)])
    write(brain.home, "greeting-guests", GREETING, **{"notes.md": "Tea is green."})
    write(brain.home, "deploying", DEPLOYING)
    write(brain.home, "broken-one", "---\nname: broken-one\n---\n")
    return brain


def test_a_skill_reads_as_claude_writes_them(tmp_path):
    skills = Skills(tmp_path / "skills")
    folder = write(tmp_path, "greeting-guests", GREETING)
    skill = skills.get("greeting-guests")
    assert not skill.error and skill.description == "Greets guests by name: warmly. Use when someone arrives."
    assert skill.argument_hint == "[name]" and skill.model and skill.user
    text = render(skill, '"Ann Lee" tomorrow')
    assert "Say hello to Ann Lee and offer tea" in text and f"{folder.as_posix()}/notes.md" in text
    assert "Tea costs $2." in text and "ARGUMENTS:" not in text  # a placeholder took them
    assert render(skills.get("greeting-guests"), "").count("$0") == 1  # nothing passed: as written
    deploy = write(tmp_path, "deploying", DEPLOYING)
    assert not skills.get("deploying").model and render(skills.get("deploying"), "v2").endswith("report: v2")
    (deploy / "SKILL.md").write_text("# Deploying\nJust do it.\n", encoding="utf-8")  # no frontmatter
    assert skills.get("deploying").description == "Deploying" and skills.get("deploying").model
    assert render(skills.get("deploying"), "now").endswith("ARGUMENTS: now")  # no placeholder: added
    assert frontmatter("---\nd: >\n  one\n  two\n\n  three\nk: |\n  a\n    b\n---\nbody") == \
        ({"d": "one two\nthree", "k": "a\n  b"}, "body")
    broken = {
        "Bad_Name": "---\ndescription: x\n---\nbody",
        "named": "---\nname: other\ndescription: x\n---\nbody",
        "tagged": "---\ndescription: uses <b>bold</b>\n---\nbody",
        "empty": "---\ndescription: x\n---\n",
        "flagged": "---\ndescription: x\nuser-invocable: sometimes\n---\nbody",
        "unclosed": "---\ndescription: x\nbody",
        "long": "---\ndescription: " + "x" * 1025 + "\n---\nbody",
    }
    for name, text in broken.items():
        write(tmp_path, name, text)
    errors = {s.name: s.error for s in skills.all()}
    assert "lowercase" in errors["Bad_Name"] and "not its folder" in errors["named"]
    assert "XML" in errors["tagged"] and "no instructions" in errors["empty"]
    assert "true or false" in errors["flagged"] and "closing ---" in errors["unclosed"]
    assert "1025 characters" in errors["long"]
    assert "skill-creator" in errors and not errors["skill-creator"]  # shipped with SentientMilk
    write(tmp_path, "skill-creator", "---\ndescription: Mine.\n---\nMy own way.")
    assert skills.get("skill-creator").description == "Mine." and not skills.get("skill-creator").builtin


def test_her_prompt_lists_the_skills_she_may_load_and_skill_use_loads_one(skilled):
    skilled.provider.replies += [tool_call("skill_use", {"name": "greeting-guests", "arguments": "Ann"}, "u1"),
                                 tool_call("skill_use", {"name": "deploying"}, "u2"),
                                 tool_call("files_read", {"path": str(skilled.home / "skills/greeting-guests/notes.md")},
                                           "r1"),
                                 "Hello Ann, tea?"]
    turn(skilled, "sk", "Ann is here")
    first, last = skilled.provider.sent[0], skilled.provider.sent[-1]
    listed = system(first).split("## SKILLS", 1)[1]
    assert "- greeting-guests: Greets guests by name" in listed and "- skill-creator: " in listed
    assert "deploying" not in listed and "broken-one" not in listed  # only the user's; broken
    assert str(skilled.home / "skills") in listed
    assert "skill_use" in [t["function"]["name"] for t in first["tools"]]  # always sent, like Claude's Skill tool
    loaded = results(last)
    assert loaded["u1"].startswith(f"Base directory for this skill: {(skilled.home / 'skills/greeting-guests').as_posix()}")
    assert "Say hello to Ann and offer tea" in loaded["u1"]
    assert "Only the user starts deploying" in loaded["u2"]
    assert "Tea is green." in loaded["r1"]  # its other files, with the file tools


def test_she_writes_a_skill_with_her_file_tools_and_it_counts_from_her_next_step(skilled):
    skill = skilled.home / "skills" / "filing-receipts" / "SKILL.md"
    good = "---\nname: filing-receipts\ndescription: Files receipts. Use when the user sends one.\n---\nFile it.\n"
    skilled.provider.replies += [
        tool_call("files_write", {"path": str(skill), "content": "---\nname: filing\n---\n"}, "w1"),
        tool_call("files_read", {"path": str(skill)}, "r1"),
        tool_call("files_write", {"path": str(skill), "content": good}, "w2"),
        tool_call("files_write", {"path": str(skilled.home / "config.json"), "content": "{}"}, "w3"),
        "Made it."]
    turn(skilled, "sk", "make a skill for receipts", on_approval=allow)
    sent = skilled.provider.sent
    assert "is broken" in results(sent[1])["w1"] and "filing-receipts" not in system(sent[1])
    assert "reads well" in results(sent[3])["w2"]
    assert "- filing-receipts: Files receipts." in system(sent[3])  # from her next step
    assert "SentientMilk's own folder" in results(sent[4])["w3"]  # its settings stay closed
    assert skilled.client.skills()[[s["name"] for s in skilled.client.skills()].index("filing-receipts")]["error"] == ""


def test_the_user_starts_a_skill_with_its_name(skilled):
    skilled.provider.replies += ["Deploying v2.", "No such skill."]
    turn(skilled, "sk", None, items=[{"type": "skill", "name": "deploying", "arguments": "v2"}])
    said = skilled.provider.last_user_text()
    assert "[The user started the skill /deploying with: v2]" in said and "report: v2" in said  # only the user's
    assert "Base directory for this skill:" in said
    entry = skilled.client.history("sk", "main")[0]
    assert entry["role"] == "user" and entry["text"] == "/deploying v2"
    preview = skilled.client.rewind_preview("sk", "main", entry["id"])
    assert preview["skills"] == ["deploying"] and preview["text"] == "/deploying v2"
    turn(skilled, "sk", None, items=[{"type": "skill", "name": "gone-now"}])
    assert "There is no such skill" in skilled.provider.last_user_text()
    assert validate_items([{"type": "skill", "name": "/deploying", "arguments": " x "}]) == \
        [{"type": "skill", "name": "deploying", "arguments": "x"}]
    for bad in ({"type": "skill"}, {"type": "skill", "name": "Bad Name"}, {"type": "skill", "name": "a", "arguments": 3}):
        with pytest.raises(ValueError):
            validate_items([bad])


def test_a_deleted_skill_comes_back_with_a_return(skilled):
    folder = skilled.home / "skills" / "greeting-guests"
    skilled.provider.replies += [tool_call("skill_delete", {"name": "greeting-guests"}, "d1"),
                                 tool_call("skill_delete", {"name": "skill-creator"}, "d2"), "Deleted."]
    turn(skilled, "sk", "delete the greeting skill", on_approval=allow)
    assert not folder.exists() and "cannot be deleted" in results(skilled.provider.sent[-1])["d2"]
    message = skilled.client.history("sk", "main")[0]["id"]
    skilled.client.rewind("sk", "main", message)
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == GREETING
    assert (folder / "notes.md").read_text(encoding="utf-8") == "Tea is green."


def test_apps_list_skills_and_the_user_removes_them(skilled):
    listed = {skill["name"]: skill for skill in skilled.client.skills()}
    assert listed["greeting-guests"]["argument_hint"] == "[name]" and listed["skill-creator"]["builtin"]
    assert not listed["deploying"]["model_invocable"] and listed["deploying"]["user_invocable"]
    assert "description" in listed["broken-one"]["error"]
    skilled.client.remove_skill("deploying")
    assert not (skilled.home / "skills" / "deploying").exists()
    for name in ("skill-creator", "never-was"):
        with pytest.raises(BrainError) as refused:
            skilled.client.remove_skill(name)
        assert refused.value.type == "bad_request"
    assert json.loads(json.dumps(skilled.client.skills()))  # plain JSON for apps
