"""Skills: her instructions for kinds of tasks, listed in her prompt and loaded when a task matches (see
``sentientmilk_framework.skills``). She makes and changes them with the file tools, in the skills folder."""

import shutil

from .. import skills as skill_files
from . import ToolContext, ToolError, Toolkit, cap, tool
from .files import keep_version


def _skill(ctx: ToolContext, name: str):
    skill = ctx.brain.skills.get(str(name or "").strip().lstrip("/"))
    if skill is None:
        raise ToolError(f"There is no skill {name!r}. SKILLS in your prompt lists the ones you can load; "
                        "skill_list shows every one, broken ones too.")
    return skill


@tool(readonly=True, core=True, rule_arg="name",
      args={"name": "The skill's name, as SKILLS lists it.",
            "arguments": "What this task is about, for the skill (optional)."})
def skill_use(ctx: ToolContext, name: str, arguments: str = ""):
    """Load a skill: its instructions for this kind of task. Before you start a task that matches a skill in
    SKILLS, load it and follow what it says. Read or run its other files only when it says to: they are in
    its base directory."""
    skill = _skill(ctx, name)
    if skill.error:
        raise ToolError(f"The skill {skill.name} is broken: {skill.error}. Its file: {skill.folder / 'SKILL.md'}")
    if not skill.model:
        raise ToolError(f"Only the user starts {skill.name} (with /{skill.name}): its SKILL.md says "
                        "disable-model-invocation: true.")
    return cap(ctx, skill_files.loaded(skill, arguments), "skill")


@tool(readonly=True)
def skill_list(ctx: ToolContext):
    """Every skill: who starts it, what it is for, where its folder is, and what is wrong with a broken one."""
    lines = []
    for skill in ctx.brain.skills.all():
        who = "you and the user" if skill.model and skill.user else "only you" if skill.model else \
            f"only the user (/{skill.name})" if skill.user else "nobody (it switches both off)"
        state = f"BROKEN: {skill.error}" if skill.error else skill.description
        origin = "comes with SentientMilk" if skill.builtin else str(skill.folder)
        lines.append(f"{skill.name} · started by {who} · {origin}\n    {state}")
    return "\n".join(lines) or "No skills yet."


@tool(rule_arg="name", args={"name": "The skill's name."})
def skill_delete(ctx: ToolContext, name: str):
    """Delete one of the user's skills: its whole folder. Returning to an earlier message brings it back."""
    skill = _skill(ctx, name)
    if skill.builtin:
        raise ToolError(f"{skill.name} comes with SentientMilk and cannot be deleted. A skill of the same name in "
                        f"{ctx.brain.skills.folder} replaces it.")
    for path in sorted(p for p in skill.folder.rglob("*") if p.is_file()):
        keep_version(ctx, path)
    shutil.rmtree(skill.folder)
    return f"Deleted the skill {skill.name} ({skill.folder})."


TOOLKIT = Toolkit("skills", "Your skills: instructions for kinds of tasks, loaded when a task needs them.",
                  [skill_use, skill_list, skill_delete])
