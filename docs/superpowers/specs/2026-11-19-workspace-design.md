# What is on her mind: a shared workspace (0.47)

Findings 2, 3 and 6 of the architecture audit (`2026-11-19-cognitive-audit-diagnosis.md`).

## Intent

What is active for her lives in separate keys (`thoughts`, `urge`, `concerns`, her tasks, what is around her,
her self-view), and each process picks from them by its own rules. A turn's note gives the last two thoughts
since the user wrote, the wish and her tasks. It never gives something she put off, an older thought about the
very thing being asked, or her self-view. A thought sees what it goes over, not what she is in the middle of.
One store of what is on her mind, written by every process and read by each by what matters to it now, makes
these the same mind.

Non-goals: no rewrite of the note's measured parts (felt sense, when, memories, leaning), no new drive.

## Approaches

- **A. A workspace beside the records** (chosen). Each process enters what it makes active, keyed by the record
  it stands for (a thought, the wish, a task, a put-off concern, a chat's matter, a surrounding, a named
  feeling, the self-view). The records stay where they are. Activation follows each item's uses. Each reader
  takes, up to her span, what is about the matter at hand first and then what is most active. The note gains
  one part, "Also on your mind", holding what it does not carry already. THINK gains the same part, and
  `look_inward` shows the whole workspace.
- B. Replace the note's parts by the workspace's selection: the parts were measured one by one (exam 58 → 64 of
  72 over 0.37-0.39), so they move one at a time, each against the current one. A is that first step.
- C. One flat list of the last N things: a recency buffer, not a competition, and N would be invented.

## Design

As built; architecture.md section 10.16 has the whole of it.

**Items** (`mind/workspace.py`, the `workspace` table in mind.sqlite3): `key`, `kind`, `text`, `episode` (the
moment it stands for: what a thought goes over is not given twice), and its uses `n`, `first`, `last`.

| kind | key | comes in | leaves |
|---|---|---|---|
| `thought` | `thought:<episode>` | her thought record, since she slept | it leaves her thoughts; her sleep |
| `intends` | `urge` | the wish her will chose | said and answered, let go, replaced |
| `put off` | `concern:<at>` | the concern | taken up or settled |
| `doing` | `task:<run>` | a task running (hers or asked) | it ends |
| `self` | `self` | her self-view | withdrawn |
| `asked` | `asked:<chat>` | a turn reads a message (its moment linked when kept) | the chat deleted; her sleep |
| `named` | `named` | she names a feeling | the next naming; her sleep |

Record-backed kinds are kept in step with her records whenever a reader looks (`Mind._in_mind`): one invariant
instead of an enter and a leave beside each of the dozen places her records change. Her sleep ends what was
before her; what she means to do stays (Goschke & Kuhl 1993). What is around her waits for 0.50.

**Activation**: ACT-R's base level, d = 0.5 (Anderson & Schooler 1991), with Petrov's (2006) approximation;
uses at one moment are that many traces of one age (found by the negative control: five uses at once counted
as one).

**Meaning by its own words**: each item's text has a vector (`workspace_vectors`), embedded by the sweep and by
a reader before it looks. By the moment an item stands for, her real "wait a month of live results" was not
found for "how are the live results looking?" (its turn was about rent and ROI); by its own words, 0.25.

**Selection**: with a cue, what she means to do now (wish, tasks), then what the cue is about (above her own
floors: her recall's for a message, `Vectors.matter` for a thought's moment), as far as her span holds. Nothing
else, however fresh: filling the span with the most active brought 4-hour-old thoughts to "what should we cook
tonight?" on her real mind, and a base level alone brings nothing back without its context (McDaniel & Einstein
2000 for what is put off). With no cue (looking inward): the most active.

**Data format 4** (`scripts/migrate_format_4.py`): the two tables, and concerns kept before they had their turn
(`run`) get it (the turn whose moment of that chat was kept first after it, if it had begun by then).

## Tests (tests/test_mind_workspace.py, tests/test_migrate_format_4.py)

- Activation: more uses and a later one keep an item more active; it fades unused; five uses at one moment are
  five traces.
- Selection: what she means to do, then what the cue is about; nothing unrelated; span 1 holds one; carried is
  left out; no cue: the most active.
- An item's words keep their meaning until they change; items leave with their records.
- Something she put off an hour ago that the message is about reaches the turn's note; fresher unrelated
  thoughts do not.
- Negative control: with the embeddings service down nothing comes by meaning, and nothing in its place.
- A thought sees her running task and her open wish, not the talk it goes over.
- Her self-view comes to a turn about it and not to an unrelated one.
- Looking inward she sees what was said in another chat.
- Her sleep ends her thoughts and what was asked; what she put off stays.
- The migration gives old concerns their turn (or None) and adds the tables; a running brain and other formats
  are left as they were.

## Measured

On a copy of her real mind (2026-11-19, format 4, her own embedder; only the messages embedded):
"how are the live results looking? has it been a month yet?" brought what she put off 14 hours ago (0.25)
and her thought about a month of waiting on the watcher; "I'm back, sorry I was gone so long" her self-view;
"is the watcher still running?" the watcher thought (0.15); "what should we cook tonight?" nothing; a thought
from her last thought, two earlier thoughts on the same matter.
