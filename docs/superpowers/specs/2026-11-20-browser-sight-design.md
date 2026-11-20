# Her browser sees what a sighted person sees — design

## Why

The user had her play a bot on chess.com in her browser (2026-11-20, "freshly open chess.com and play a match
with a bot, I'm testing something"). She made 133 `browser_script` calls and 13 `browser_act` calls. She drove
the game by firing synthetic pointer events at the site's own board object, because her browser tools hid the
game from her and misreported what her clicks did. The user's words: the browser part "conceals information
from her, and doesn't allow to interact with browser freely". They asked for a general fix, not chess code.

## What failed (measured in her sessions and in a stand-in Edge on chess.com)

1. **The view drops what has no words.**
   - The board's 32 pieces are `div.piece.wp.square-52` with background pictures, so the view showed only
     "Starting Position".
   - The bot's speech is `aria-hidden` but shown on screen, and the view dropped it.
   - Icon-only controls came through nameless (`button e135`). Each is a picture file such as
     `white--sm.svg`, `random.svg` or `black--sm.svg`.
2. **Two pixel spaces.**
   - Points were in the latest picture's pixels: the device picture scaled to 1641 px wide.
   - Scripts measure page pixels, 1266 px wide (0.77 of the picture).
   - Her script-measured points hit the wrong squares, and a point before any picture was refused.
3. **Act replies lied.** "Nothing changed on the page" came back while the board had changed: only words
   were compared.
4. **Noise.** An ad frame re-made with new ids added three -/+ lines to every reply.
5. **Friction.**
   - `return` at a script's top level failed with "Illegal return statement" (4 times).
   - Waiting for the opponent took a script sleep.

## Goals

- Everything a sighted person sees on the page reaches her: in words, with an id when it can be acted on,
  and with its place when the place matters.
- One pixel space everywhere: page pixels (CSS pixels of the tab's window). Pictures, points, view boxes and
  a script's `getBoundingClientRect()` all agree.
- An act's reply never says nothing changed when something visibly did.
- Real input (trusted events) is the natural way to act on anything. Scripts are for data, not for clicking.

## Non-goals and anti-goals

- No per-site or per-game code. No list of known sites, no game knowledge.
- No ids drawn onto pictures. Computer use measured that drawn marks cost reading and doubled misreads.
- No accessibility-tree view. It is built for screen readers and drops exactly what failed here.

## Approaches

- **A (chosen): extend the text view and the act loop.** The view describes wordless things from the page's
  own vocabulary. Pictures are in page pixels, and acts report every visible change.
- **B: set-of-marks pictures.** Rejected: drawn marks cost reading accuracy in computer use, and B fixes neither
  change reports nor the text view.
- **C: Chrome's accessibility tree.** Rejected for the reason above.

## Design

1. **Wordless things.** A shown element with no words of its own is described by what the page itself calls it:
   - its label, title or alt;
   - otherwise its picture: its own or a child's image or background file name (`"white--sm.svg"`), or an
     svg `<use>` href or title;
   - otherwise its class words, with build hashes dropped (`.piece.wp.square-52`);
   - otherwise its background colour.

   The same fallback names nameless controls (`button e135 "white--sm.svg"`) and what an act's point landed
   on.
2. **Scenes.** A container with 3 or more shown, wordless children is a scene: a board, a grid of cells, a map's
   markers, a row of icons.
   - It is shown as `scene e180 wc-chess-board.board @222,66 512x512`.
   - Each wordless child gets a line with its id and box: `picture e183 "wp.png" .piece.wp.square-52
     @478,450 64x64`.
   - Children with words are shown as usual.
   - A scene longer than 100 things shows its first 100, and `part=` shows the rest, like long lists.
   - Canvases and videos get ids and boxes too.
3. **Boxes on request.** `browser_view boxes=true` adds `@x,y wxh` to every thing with an id.
   - Boxes are where things are in the window now, in page pixels.
   - Frames of another site have their offset added.
4. **Visible words are read.**
   - Words in `aria-hidden` parts are read when they are shown.
   - Icon-font glyphs (Unicode private use areas) are dropped everywhere: they are not words.
5. **Page pixels.**
   - A picture is the window scaled to page pixels, so a picture pixel is a page pixel.
   - Points are page pixels and need no picture first. A point outside the window is refused, naming its
     size.
   - When `image_pixels` forces a smaller picture, its caption gives the scale.
6. **Honest act replies.**
   - Scene lines carry boxes and classes, so moved, added and removed things show in the -/+ diff.
   - Before an act, a small grey frame of the window is kept. When no words changed after it, but the window's
     pixels did, the reply names each changed region and what is there.
   - A minimized window is not pictured.
   - Lines that only got new ids (and a link's query string) collapse into one line naming the new ids.
   - `browser_act picture=true` adds a picture after the steps. It is skipped, with a note, when the page holds
     what the user typed.
7. **Waiting for a part.** A `wait` step with a target and no text waits until that part's words, boxes or
   pixels change, for at most `amount` seconds (default 20). A canvas works too, through pixels.
8. **Scripts.** A top-level `return` works: on that syntax error, the code runs again as the body of an
   async function. Nothing ran the first time.
9. **Words she reads.** `GUIDE`, the argument texts and `docs/architecture.md` describe the above. MilkChan's
   chat rows name a wait for a change, `boxes` and an act's picture.

## Verification

- `tests/test_browser.py` gets new local pages:
  - a board of wordless tiles that takes only trusted clicks and answers after a delay;
  - an aria-hidden speech line;
  - an icon button;
  - a canvas that redraws on click without words;
  - a link re-made on each click.

  There is a test for each part of the design.
- MilkChan `scripts/eval_browser.py` gets board tasks: tic-tac-toe on wordless tiles and on a canvas, against
  a bot that answers after a delay. Only trusted clicks count. A task passes when the game ended and she did
  not lose. Each is run with her real model, before (previous SentientMilk) and after.
- One live run on chess.com in the stand-in Edge, before and after, counts act versus script calls.
