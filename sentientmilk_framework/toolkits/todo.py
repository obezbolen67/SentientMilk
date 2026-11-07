"""Todo: the model's own plan for multi-step work, rewritten whole each time (recitation)."""

from . import ToolContext, ToolError, Toolkit, tool

STATUSES = {"pending": " ", "doing": ">", "done": "x"}
ITEMS = {"type": "array", "description": "The whole list, in order.",
         "items": {"type": "object", "required": ["text", "status"],
                   "properties": {"text": {"type": "string"}, "status": {"type": "string", "enum": list(STATUSES)}}}}


def render(items: list) -> str:
    if not items:
        return "The todo list is empty."
    return "\n".join(f"{n}. [{STATUSES[item['status']]}] {item['text']}" for n, item in enumerate(items, 1))


@tool(core=True, policy="auto", args={"items": ITEMS})
def todo_write(ctx: ToolContext, items: list):
    """Keep a todo list for work with three or more steps: write it before you start, then send the whole
    updated list each time an item starts (doing) or ends (done). Keep at most one item doing. The list
    survives when older context is summarized, so it is how you keep track of long work."""
    if not isinstance(items, list) or not all(
            isinstance(i, dict) and isinstance(i.get("text"), str) and i.get("status") in STATUSES for i in items):
        raise ToolError("items must be a list of {text, status} with status pending, doing or done.")
    items = [{"text": i["text"].strip(), "status": i["status"]} for i in items if i["text"].strip()]

    def change(state):
        state["todo"] = items
        return state
    ctx.store.update_session(ctx.app, ctx.session, "state", change)
    return render(items)


TOOLKIT = Toolkit("todo", "A todo list for multi-step work.", [todo_write])
