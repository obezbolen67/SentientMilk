"""A model may choose a safe continuation boundary after finishing a unit of work."""

from . import ToolContext, ToolError, Toolkit, tool


@tool(core=True, policy='auto', args={'note': 'Progress, decisions and the next unfinished action.'},
      guide='At a completed milestone during long work, use context_compact with progress and next steps. '
            'Keep your todo current. Original evidence remains available through history_read/search.')
def context_compact(ctx: ToolContext, note: str):
    """Checkpoint and compact your own context at the next safe boundary, after this batch of tools settles.
    Give exact references and remaining work; this preserves history and never repeats a tool."""
    if not isinstance(note, str) or not note.strip():
        raise ToolError('Give a progress note and the next unfinished action.')
    ctx.store.update_run_options(ctx.run['id'], lambda options: {**options, 'compact_requested': note.strip()})
    return 'Checkpoint requested. Continue from your next unfinished action after compaction.'


TOOLKIT = Toolkit('continuation', 'Keep continuity across long work.', [context_compact], part=True)
