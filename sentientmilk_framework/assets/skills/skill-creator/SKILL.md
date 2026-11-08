---
name: skill-creator
description: Writes new skills and improves existing ones. Use when the user asks to make, change, fix or delete a skill, or wants a task they just did with you done the same way next time.
---

# Making skills

A skill is a folder in the skills folder (named in SKILLS in your prompt) holding a SKILL.md: frontmatter, then
instructions. Its name and description sit in your prompt in every app; the instructions load only when a task
matches. Write skills with files_write and files_edit; deleting one is skill_delete.

## Steps

1. Know the task. Find out what the skill is for from a real example: what the user asks, what a good result
   looks like, what went wrong before. Ask when this is unclear; do not guess a whole workflow.
2. Pick the name: 1-64 lowercase letters, numbers and hyphens, the folder's name too. Prefer a verb in -ing
   form that says the job: `writing-release-notes`, `filing-receipts`. Not `helper`, `utils` or `stuff`.
3. Write the description, the only part you see before you load it: say what the skill does and when to use
   it, in the third person, with the words a user would say. At most 1024 characters, no XML tags.
   Good: "Files receipt photos into the expenses sheet by date and amount. Use when the user sends a receipt
   or asks to log an expense." Bad: "Helps with receipts."
4. Write the instructions:
   - Only what you would not know or do anyway. Every line costs tokens each time it loads.
   - Numbered steps for a workflow, one default way (with an escape hatch) rather than a menu of options.
   - For long or risky work: a checklist to copy into the reply and tick off, and a check-fix-repeat loop.
   - Under 500 lines. Put detail into other files beside SKILL.md, one level deep, each linked from SKILL.md
     with when to read it ("For the column rules, read sheet-rules.md").
   - Scripts for steps that must be exact: say whether to run one ("Run scripts/check.py") or read it.
   - Write paths to its files as `${SKILL_DIR}/scripts/check.py`, with forward slashes: they become the
     skill's folder.
   - `$ARGUMENTS` is what the user typed after /name (or the arguments you load it with); `$0`, `$1` its words.
   - No secrets in a skill: it is plain text on the user's disk.
5. Save it: files_write `<skills folder>/<name>/SKILL.md`, then its other files. The result says whether the
   skill reads well, or what to fix.
6. Try it: load it with skill_use on a realistic example and follow it. Fix what was unclear or missing.
7. Tell the user its name, what makes you use it, and that they can start it themselves with /name.

## SKILL.md

```markdown
---
name: filing-receipts
description: Files receipt photos into the expenses sheet by date and amount. Use when the user sends a receipt or asks to log an expense.
argument-hint: "[month]"
---

# Filing receipts

1. ...
```

Optional fields:
- `argument-hint`: what to type after /name, shown to the user.
- `disable-model-invocation: true`: only the user starts it (/name), for things they want to time themselves,
  such as sending or publishing.
- `user-invocable: false`: only you load it, for background knowledge that is no command.

## Changing a skill

Read its SKILL.md with files_read first, then change it with files_edit; keep its name. A skill that comes with
SentientMilk cannot be changed in place: write one of the same name in the skills folder, which replaces it.
