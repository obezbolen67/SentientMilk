# SentientMilk

SentientMilk is the OpenAI-compatible model and tool-calling layer used by the
MilkChan desktop assistant. It discovers Python tools, derives JSON schemas from
their signatures, executes model-requested tools, and supports streaming and
non-streaming chat completions.

## Development

Use Python 3.12. From this repository:

```bash
python -m venv .venv
# Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,cli,desktop-tools]"
python -m pytest -q
python -m ruff check .
```

Run the optional terminal client with `sentientmilk-chat`.

## Basic usage

```python
from sentientmilk_framework import Conversation, LLM, Settings

llm = LLM(
    api_key="your-key",
    base_url="https://api.openai.com/v1",
    model="gpt-4.1-mini",
    settings=Settings(persona="Be concise.", custom_tools_path="./tools"),
)
conversation = Conversation(path="conversation.sqlite3")
conversation.append({"role": "user", "content": "Read notes.txt and summarize it."})
result = llm.completion(conversation)
print(result["choices"][0]["message"]["content"])
print(llm.last_usage)
```

A tool is a Python module with a `run` function. Its annotations become the
tool's input schema:

```python
def run(path: str, offset: int = 0, limit: int = 200) -> str:
    """Read a range of lines from a text file."""
    ...
```

Tool calls are bounded by `max_tool_rounds` (default: 8). Lifecycle events sent
to an optional event handler include a stable `call_id`, allowing consumers to
match concurrent starts and results.

## Repository layout

```text
sentientmilk_framework/
  ai.py                 LLM transport, streaming, and tool orchestration
  tools/                Built-in filesystem, shell, and web tools
chat_cli.py             Optional Rich terminal client
main.py                 Small interactive example
tests/                  Protocol and tool regression tests
```

MilkChan integration and combined development commands live in the sibling
MilkChan repository.
