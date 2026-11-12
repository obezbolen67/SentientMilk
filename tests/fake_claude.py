"""A stand-in for the user's Claude Code in tests: its headless protocol, as far as SentientMilk uses it.

It answers ``initialize`` with its models and account (FAKE_SIGNED_OUT: none), logs how it was started and
what it was told to FAKE_LOG, and does what the prompt says. With the host's MCP server (--mcp-config with a
server of type sdk) it is the brain's provider: ``CALL name {json}`` calls her tool and tells its result,
``LIMIT`` hits the plan's limit, ``slow`` takes a minute, anything else is echoed. Without, it is a super agent,
with Claude Code's own tools (write, mcp, race, wait, crash, slow).
"""

import json
import os
import re
import sys
import time

args = sys.argv[1:]
LOG = os.environ.get("FAKE_LOG")
MODELS = [
    {"value": "default", "resolvedModel": "claude-opus-9", "displayName": "Default (recommended)",
     "description": "Opus 9 · Best for everyday, complex tasks", "supportsEffort": True,
     "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
    {"value": "opus", "resolvedModel": "claude-opus-9", "displayName": "Opus 9", "description": "For complex work",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high", "xhigh", "max"]},
    {"value": "sonnet", "resolvedModel": "claude-sonnet-9", "displayName": "Sonnet 9", "description": "Efficient",
     "supportsEffort": True, "supportedEffortLevels": ["low", "medium", "high"]},
    {"value": "haiku", "resolvedModel": "claude-haiku-9", "displayName": "Haiku 9", "description": "Fastest",
     "supportsEffort": False},
]
SIGNED_OUT = bool(os.environ.get("FAKE_SIGNED_OUT"))
ACCOUNT = {"tokenSource": "none", "apiKeySource": "none"} if SIGNED_OUT else {
    "email": "user@example.com", "organization": "Example", "subscriptionType": "Claude Max", "apiProvider": "firstParty"}


def value(flag):
    return args[args.index(flag) + 1] if flag in args else None


def log(entry):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as output:
            output.write(json.dumps(entry) + "\n")


def mcp_config():
    raw = value("--mcp-config")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        with open(raw, encoding="utf-8") as config:
            return json.load(config)


def read_file(flag):
    path = value(flag)
    if path is None:
        return None
    with open(path, encoding="utf-8") as prompt:
        return prompt.read()


mcp = mcp_config()
provider = bool(mcp) and any(s.get("type") == "sdk" for s in mcp["mcpServers"].values())
log({"args": args, "cwd": os.getcwd(), "mcp": mcp, "system": read_file("--system-prompt-file"),
     "appended": read_file("--append-system-prompt-file"), "provider": provider})
resumed = value("--resume")
session = resumed or f"claude-session-{os.getpid()}" if provider else resumed or "claude-session-1"
if resumed == "gone-session":  # Claude Code deleted it (it keeps them 30 days)
    sys.stderr.write("No conversation found with session ID: gone-session\n")
    sys.stdout.write(json.dumps({"type": "result", "subtype": "error_during_execution", "is_error": True,
                                 "num_turns": 0, "session_id": resumed}) + "\n")
    sys.exit(1)


def out(event):
    sys.stdout.write(json.dumps(event) + "\n")
    sys.stdout.flush()


said_meanwhile = []  # user messages that came while it waited for an answer of the host's
numbers = iter(range(1, 1000))


def answer_initialize(event):
    out({"type": "control_response", "response": {"subtype": "success", "request_id": event["request_id"], "response": {
        "models": MODELS, "account": ACCOUNT, "claude_code_version": "9.9.9", "commands": []}}})


def next_line():
    """The next line of stdin that is not Claude Code's own business (initialize is answered at once)."""
    for line in sys.stdin:
        event = json.loads(line)
        if event["type"] == "control_request" and event["request"]["subtype"] == "initialize":
            answer_initialize(event)
            continue
        return event
    sys.exit(0)


def message():
    """The next user message's content, or an answer of the host's (super agent mode)."""
    while True:
        event = next_line()
        if event["type"] == "user":  # taken in: it says so (--replay-user-messages)
            out({"type": "user", "isReplay": True, "message": event["message"]})
            return event["message"]["content"]
        if event["type"] == "control_response":
            return event["response"]["response"]


def text_of(content):
    if isinstance(content, str):
        return content
    return "\n".join(b.get("text", "") if b.get("type") == "text" else "[image]" for b in content)


def said(text):
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": text}]}})


def result(text, error=False, subtype="success"):
    out({"type": "result", "subtype": subtype, "is_error": error, "result": text, "num_turns": 2,
         "session_id": session, "total_cost_usd": 0.01,
         "usage": {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100,
                   "output_tokens": 7},
         "modelUsage": {next(m["resolvedModel"] for m in MODELS if m["value"] == (value("--model") or "default")):
                        {"inputTokens": 10, "outputTokens": 7, "contextWindow": 900000, "maxOutputTokens": 64000}}})


# ============== As the brain's provider ==============

def ask_host(subtype, body):
    """A control request to the host, and its answer; user messages meanwhile are kept for the next request."""
    request_id = f"req-{next(numbers)}"
    out({"type": "control_request", "request_id": request_id, "request": {"subtype": subtype, **body}})
    while True:
        event = next_line()
        if event["type"] == "user":
            said_meanwhile.append(event["message"]["content"])
            log({"meanwhile": event["message"]["content"]})
        elif event["type"] == "control_response" and event["response"]["request_id"] == request_id:
            return event["response"].get("response") or {}


def mcp_call(method, params, mid):
    message_ = {"jsonrpc": "2.0", "method": method, "params": params}
    if mid is not None:
        message_["id"] = mid
    return ask_host("mcp_message", {"server_name": "milk", "message": message_}).get("mcp_response") or {}


def stream(blocks, stop):
    """One API message as Claude Code passes it on: stream events (--include-partial-messages) and an
    assistant event per block."""
    mid = f"msg_{next(numbers)}"
    usage = {"input_tokens": 3, "cache_creation_input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 1}
    out({"type": "stream_event", "event": {"type": "message_start", "message": {"id": mid, "usage": usage}}})
    for index, block in enumerate(blocks):
        start = {"type": "text", "text": ""} if block["type"] == "text" else {**block, "input": {}}
        out({"type": "stream_event", "event": {"type": "content_block_start", "index": index, "content_block": start}})
        whole = block["text"] if block["type"] == "text" else json.dumps(block["input"])
        for piece in (whole[:len(whole) // 2], whole[len(whole) // 2:]):
            delta = {"type": "text_delta", "text": piece} if block["type"] == "text" else \
                {"type": "input_json_delta", "partial_json": piece}
            out({"type": "stream_event", "event": {"type": "content_block_delta", "index": index, "delta": delta}})
        out({"type": "assistant", "message": {"id": mid, "content": [block]}})
        out({"type": "stream_event", "event": {"type": "content_block_stop", "index": index}})
    out({"type": "stream_event", "event": {"type": "message_delta", "delta": {"stop_reason": stop},
                                           "usage": {**usage, "output_tokens": 7}}})
    out({"type": "stream_event", "event": {"type": "message_stop"}})


def be_provider():
    mcp_call("initialize", {"protocolVersion": "2025-11-25"}, 0)
    mcp_call("notifications/initialized", {}, None)
    tools = mcp_call("tools/list", {}, 1).get("result", {}).get("tools", [])
    log({"tools": [t["name"] for t in tools]})
    out({"type": "system", "subtype": "init", "session_id": session, "tools": ["mcp__milk__" + t["name"] for t in tools]})
    while True:
        if said_meanwhile:  # sent while it started up: its first turn
            content = said_meanwhile.pop(0)
        else:
            event = next_line()
            if event["type"] != "user":
                continue
            content = event["message"]["content"]
        log({"said": content})
        text = text_of(content)
        if SIGNED_OUT:
            out({"type": "assistant", "error": "authentication_failed",
                 "message": {"content": [{"type": "text", "text": "Not logged in · Please run /login"}]}})
            result("Not logged in · Please run /login", error=True)
            continue
        if "LIMIT" in text:
            out({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": 1900000000}})
            out({"type": "assistant", "error": "rate_limit",
                 "message": {"content": [{"type": "text", "text": "You've hit your limit"}]}})
            result("You've hit your limit", error=True)
            continue
        if "slow" in text.splitlines()[-1]:
            time.sleep(60)
        calls = re.findall(r"CALL (\w+) (\{.*?\})(?=\s*(?:CALL|$))", text.splitlines()[-1])
        if calls:
            uses = [{"type": "tool_use", "id": f"toolu_{next(numbers)}", "name": "mcp__milk__" + name,
                     "input": json.loads(arguments)} for name, arguments in calls]
            stream([{"type": "text", "text": "Calling."}] + uses, "tool_use")
            results = []
            for use in uses:
                ask_host("can_use_tool", {"tool_name": use["name"], "input": use["input"], "tool_use_id": use["id"]})
                answer = mcp_call("tools/call", {"name": use["name"][len("mcp__milk__"):], "arguments": use["input"],
                                                 "_meta": {"claudecode/toolUseId": use["id"]}}, next(numbers))
                got = text_of(answer["result"]["content"])
                out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": use["id"],
                                                              "content": got}]}})
                results.append(got)
            reply = "result: " + " / ".join(results)
            if said_meanwhile:
                reply += " | then: " + " / ".join(text_of(c) for c in said_meanwhile)
                said_meanwhile.clear()
        else:
            reply = ("resumed " if resumed else "") + "echo: " + text.splitlines()[-1]
        stream([{"type": "text", "text": reply}], "end_turn")
        result(reply)


# ============== As a super agent ==============

def be_super():
    out({"type": "system", "subtype": "init", "session_id": session})
    while True:
        text = message()
        if not isinstance(text, str):
            text = text_of(text)
        if "brain restarted" in text:  # it goes on where it was: in these tests, the write
            text = "write"
        if "is gone" in text:
            result("anew: " + " | ".join(text.splitlines()))
            continue
        if "crash" in text:
            sys.stderr.write("boom\n")
            sys.exit(3)
        if SIGNED_OUT:
            out({"type": "assistant", "error": "authentication_failed",
                 "message": {"content": [{"type": "text", "text": "Not logged in · Please run /login"}]}})
            result("Not logged in · Please run /login", error=True)
        elif "write" in text:
            path = os.path.join(os.getcwd(), "out.txt")
            out({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "toolu_1", "name": "Write", "input": {"file_path": path, "content": "made"}}]}})
            out({"type": "control_request", "request_id": "r1", "request": {
                "subtype": "can_use_tool", "tool_name": "Write", "tool_use_id": "toolu_1",
                "input": {"file_path": path, "content": "made"}}})
            answer = message()
            if answer["behavior"] == "allow":
                with open(path, "w") as output:
                    output.write(answer["updatedInput"]["content"])
                out({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "File created"}]}})
                said("Wrote out.txt.")
                result("Wrote out.txt.")
            else:
                out({"type": "user", "message": {"content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": answer["message"], "is_error": True}]}})
                result("Could not write: " + answer["message"])
        elif "mcp" in text:
            out({"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "toolu_2", "name": "mcp__editor__save", "input": {"scene": "main"}}]}})
            out({"type": "control_request", "request_id": "r2", "request": {
                "subtype": "can_use_tool", "tool_name": "mcp__editor__save", "tool_use_id": "toolu_2",
                "input": {"scene": "main"}}})
            answer = message()
            result("saved" if answer["behavior"] == "allow" else "refused")
        elif "race" in text:  # it finishes only once the test has sent it a message
            said("Part A.")
            while not os.path.exists(os.environ["FAKE_GO"]):
                time.sleep(0.02)
            result("Did A.")
        elif "slow" in text:
            time.sleep(60)
        elif "wait" in text:
            said("Waiting for the lead.")
            result("got: " + text_of(message()))
        else:
            result(("resumed " if resumed else "") + "echo: " + text.splitlines()[-1])


if "--no-session-persistence" in args and "--model" not in args:  # a question about itself: initialize only
    while True:
        next_line()
elif provider:
    be_provider()
elif "--model" in args and value("--system-prompt-file"):  # a one-off call of the brain's (titles, compaction)
    while True:
        event = next_line()
        if event["type"] == "user":
            log({"said_once": event["message"]["content"]})
            reply = "once: " + text_of(event["message"]["content"]).splitlines()[-1]
            stream([{"type": "text", "text": reply}], "end_turn")
            result(reply)
else:
    be_super()
