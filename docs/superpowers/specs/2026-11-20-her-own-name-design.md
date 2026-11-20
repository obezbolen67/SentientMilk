# Her own name (0.54)

## Why

A user's companion chose her own name one night. The next afternoon, when the user called her by it, she took
it as a new name she had just been handed. The name was in her memories (the moments she chose it, and an insight
she had about it). Nothing kept it in front of her:

- Her system prompt said "In this app you are called <the app's character name>". Her installed persona said
  she doesn't remember her name and is upset by that very name.
- She knows the people in her life by name (people.py), but not herself.
- Her nightly self-view said "I chose my own name" without the name, and it never reaches a chat anyway.
- The name was in one chat's session memory only (`memory_save`).

A person's own name is the most overlearned thing they know about themselves. It is always at hand, and it
outweighs what others label them.

## Approaches

1. **Learned in sleep, like the people in her life (chosen).** The people step already goes over what happened
   each night and settles who people are. The same step settles the name she goes by now, from what she lived
   through. Nothing is typed in or hardcoded, and it changes the way a person's name changes (a new name: the
   old one becomes another of hers).
2. *A name field in the app's settings.* Typed in by someone, not hers. It's the same as the persona line.
3. *Her self-view keeps the name.* A model-written paragraph might drop it again, and it doesn't reach chats.

## Design

- `People.me`: `{"name", "aka", "since", "origins"}`, or None until a night settles it. `People.name_me(change,
  now, origins)` sets it. A different name makes the old one another of hers. She is never one of the people in
  her life: `update` skips a change that names her, and drops her names from anyone's aka.
- The people step (`prompts.PEOPLE`) is told "Their own name: ..." (or "not settled yet"). It may answer
  `"self": {"name", "aka"}` only when what happened shows the name they call themselves (one they chose, or
  were given and took). The app's name for them is not that. A name is taken only if a moment it went over
  says it (as for people), and those moments are its origins.
- Every chat's prompt (`context.system_prompt`, agents included) opens with "Your name is X (also ...): the
  name you go by now, whatever the description below says of your name. This app shows you as <app name>."
  It comes from the session's snapshot (`snapshot["me"]`), which is taken again when sleep changes it.

No data change: `me` is a new key of the people record, absent until her first night that settles it. Her next
sleep goes over the day's moments, which name her.
