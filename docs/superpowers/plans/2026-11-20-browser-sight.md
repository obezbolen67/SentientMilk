# Browser Sight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everything a sighted person sees on a page reaches her, in one pixel space. Every visible change an act
makes is reported, and real input acts on anything she sees.

**Architecture:**

- `browser_page.js` (her isolated world) describes wordless things, scenes, boxes and aria-hidden words.
- `browser.py` takes pictures in page pixels, takes points in page pixels, compares frames for pixel changes,
  collapses re-made lines, waits for a part to change, and retries scripts with a top-level return.
- `toolkits/browser.py` carries the new arguments and words.

**Tech Stack:** Python 3.12, Chrome DevTools Protocol through SentientMilk's extension, Pillow, pytest with the
stand-in Edge on a hidden desktop.

**Spec:** `docs/superpowers/specs/2026-11-20-browser-sight-design.md`

## Global Constraints

- No site- or game-specific code, and no list of sites.
- Page pixels are the only coordinates she is given or gives.
- No ids drawn onto pictures.
- No legacy shims: `Tab.picture` stays only as the scale of a picture smaller than page pixels.
- Tests run only in the stand-in Edge on a hidden desktop, never on the user's screen.
- Commits use the git-commit skill, with no Claude attribution.

## Review Focus

- **A page that never stops animating (ads, video).** The pixel note names those regions. It must not hide a
  real word change. Pinned in Task 3 by the canvas test, where words do not change.
- **A focused text field's blinking caret.** It must not be reported as a picture change. Pinned in Task 3
  (fill, then an act that changes nothing).
- **Huge scenes (a 30x16 grid).** The view stays bounded: 100 things, then `part=`. Pinned in Task 1.
- **Frames of another site with boxes.** Boxes there include the frame's offset. Pinned in Task 1, on the
  existing frames page.
- **A point outside the window.** It is refused, naming the window's size. Pinned in Task 2.

---

### Task 1: The view sees wordless things, scenes, boxes and shown aria-hidden words

**Files:**
- Modify: `sentientmilk_framework/browser_page.js`
- Modify: `sentientmilk_framework/browser.py` (`_view` and `_frame_text` pass `boxes` and `origin`)
- Test: `tests/test_browser.py` (new pages `/board` and `/grid`)

**Interfaces:**
- Produces:
  - `__milk.view({full, part, texts, boxes, origin:[x,y]})`
  - `looks(el) -> str`, the fallback name
  - `box(el) -> "@x,y wxh"`
  - `__milk.at` labels use `looks`

- [ ] Write `test_wordless_things_are_seen_by_what_the_page_calls_them`. It asserts:
  - a `scene e\d+` line;
  - `picture e\d+ "x.svg" .piece.x.cell-1 @\d+,\d+ \d+x\d+`;
  - an icon button named by its file;
  - the aria-hidden speech words.
- [ ] Write `test_a_big_scene_shows_its_start_and_the_rest_by_part` (`/grid`: 480 cells → 100, then `part=`).
- [ ] Write `test_boxes_are_given_on_request_in_frames_too` (frames page: a box inside another site's frame is
  larger than the frame's own left).
- [ ] Implement, then run `pytest tests/test_browser.py -k "wordless or big_scene or boxes"`. Expected: all
  pass.

### Task 2: Pictures and points in page pixels

**Files:**
- Modify: `browser.py` (`_picture`, `_point`, `view` caption)
- Modify: `tests/test_browser.py` (`test_what_has_no_id_is_pointed_at_in_a_picture`)
- Modify: `tests/test_artifacts.py` (pay by point)

- [ ] Change the tests:
  - a picture's size equals `[innerWidth, innerHeight]`;
  - a click at a canvas point needs no picture first;
  - a point outside the window is refused with "outside the tab's window".
- [ ] `_picture` resizes the capture to `innerWidth x innerHeight`, and `Tab.picture` is set only when the
  budget shrank it further.
- [ ] `_point` takes page pixels and divides by nothing.
- [ ] Run `pytest tests/test_browser.py tests/test_artifacts.py -k "point or pays"`.

### Task 3: Act replies say every visible change; act can return a picture

**Files:**
- Modify: `browser.py` (`act`, `_changes`, new `_glance`, `_regions`)
- Modify: `toolkits/browser.py` (`browser_act` `picture`)
- Test: `tests/test_browser.py` (pages `/board`, `/canvas`, `/remade`)

**Interfaces:**
- Produces:
  - `Browser.act(ctx, steps, tab="", picture=False) -> ToolResult`
  - `_glance(tab) -> Optional[Image]` (grey, a quarter of page pixels)
  - `_regions(before, after) -> List[tuple]` (page-pixel boxes)

- [ ] Write the tests:
  - `test_an_act_says_what_moved_in_a_scene`;
  - `test_a_change_only_in_pixels_is_said_with_where`;
  - `test_things_made_anew_are_one_line`;
  - `test_a_caret_is_not_a_change`;
  - `test_an_act_can_end_with_a_picture`.
- [ ] Implement them, then run the tests.

### Task 4: A wait for a part to change; scripts with a top-level return

**Files:**
- Modify: `browser.py` (`_wait`, `script`)
- Test: `tests/test_browser.py`

- [ ] Write the tests:
  - `test_a_wait_ends_when_a_part_changes`: the board's bot answers after 1.5 s, and `wait` with a target
    returns within 5 s, naming the change;
  - `test_a_script_may_return_at_its_top`: `return 1 + 1` gives `2`.
- [ ] Implement them, then run the tests.

### Task 5: Her words, docs and MilkChan

**Files:**
- Modify: `toolkits/browser.py` (`GUIDE`, `STEP`, args)
- Modify: `docs/architecture.md`
- Modify: MilkChan `milkchan/desktop/ui/chat_format.py` and `tests/test_chat_format.py`
- Modify: MilkChan `scripts/eval_browser.py`
- Create: MilkChan `tests/board_site.py`

- [ ] Rewrite the words.
- [ ] Add MilkChan rows: "wait for X to change", "boxes", "picture".
- [ ] Add the board eval tasks `tiles` and `canvas`.
- [ ] Run the full SentientMilk suite, the MilkChan chat_format tests, and the eval before and after (3 runs
  each), plus one chess.com live run before and after.
- [ ] Commit, push, pin, rebuild.
