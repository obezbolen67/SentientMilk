# SentientMilk Framework

An intelligent LLM framework with integrated MCP (Model Context Protocol) support for building AI-powered applications.

## Features

- 🤖 **LLM Integration**: Easy-to-use interface for language models
- 🔧 **MCP Support**: Standardized tool and resource integration
- 🌐 **Web Search**: Built-in internet search capabilities
- 🎤 **Voice Integration**: Text-to-speech with ElevenLabs
- 🔥 **Firebase Support**: Database integration out of the box
- 🔌 **Extensible**: Add custom tools and integrations easily
- 🖥️ **Desktop Assistant**: Full desktop and file system control - Like Jarvis, but SentientMilk!

## 🆕 Desktop Assistant - NEW!

**Experience the power of AI-controlled desktop automation!**

The SentientMilk Desktop Assistant is a fully-featured AI assistant with comprehensive desktop and file system control capabilities.

### Quick Start

```bash
# Windows
run_desktop_assistant.bat

# Linux/macOS
./run_desktop_assistant.sh
```

### Capabilities

- **🖱️ Desktop Control**: Mouse, keyboard, clipboard, screenshots
- **📁 File System**: Read, write, create, delete, search files and directories
- **🪟 Window Management**: Minimize, maximize, close windows
- **🚀 Smart App Launching**: Auto-detects browsers, text editors; handles generic requests like "open browser"
- **🔍 Web Search**: Search the internet for current information
- **🗣️ Voice Output**: Text-to-speech for responses

### Example Commands

```
"Take a screenshot and save it"
"List all Python files in my Documents folder"
"Create a new folder called Projects"
"Search for all .txt files containing 'TODO'"
"Open my browser"  # Smart detection of available browsers
"Open Google in my browser"  # Opens URL directly
"What browsers do I have installed?"  # Detects available apps
"What's in my clipboard?"
```

See **[Desktop Assistant Guide](DESKTOP_ASSISTANT_GUIDE.md)** for complete documentation.

## Quick Start

### Installation

```bash
pip install -r requirements.txt  # Install dependencies
```

### Try the CLI Chat App

Experience all features with our beautiful CLI chat interface:

```bash
python chat_cli.py
```

Or on Windows, just double-click: `run_chat.bat`

See [CLI Chat Guide](CLI_CHAT_GUIDE.md) for full documentation.

### Basic Usage

```python
from sentientmilk_framework import LLM, Settings

# Initialize the LLM
ai_model = LLM(
    api_key="your_api_key",
    base_url="https://your-endpoint.com",
    settings=Settings(persona="You are a helpful assistant")
)

# Generate a response
response = ai_model.completion(
    model="gemini-2.5-flash",
    messages=[
        {"role": "user", "content": "Hello!"}
    ]
)
```

### With MCP Tools

```python
from sentientmilk_framework import LLM, MCPServer, MCPTool, MCPParameter

# Create MCP server and register tools
mcp_server = MCPServer()

def calculate(expression: str) -> str:
    return str(eval(expression))

calc_tool = MCPTool(
    name="calculate",
    description="Perform mathematical calculations",
    parameters=[
        MCPParameter(name="expression", type="string", 
                    description="Math expression", required=True)
    ],
    handler=calculate,
    category="math"
)

mcp_server.register_tool(calc_tool)

# Use with LLM
ai_model = LLM(
    api_key="your_api_key",
    mcp_server=mcp_server
)

# The AI can now use your tools!
response = ai_model.completion(
    model="gemini-2.5-flash",
    messages=[
        {"role": "user", "content": "What's 15 times 23?"}
    ]
)
```

## Project Structure

```
MilkChanAPI/
├── app.py                          # Flask API server
├── test.py                         # Test script
├── example_mcp_usage.py            # MCP examples
├── sentientmilk_framework/
│   ├── __init__.py                 # Package exports
│   ├── ai.py                       # Core LLM class
│   ├── mcp.py                      # MCP implementation
│   ├── integrations.py             # Voice, Internet, etc.
│   └── types.py                    # Type definitions
├── MCP_USAGE.md                    # MCP documentation
├── MIGRATION_GUIDE.md              # Migration guide
└── MCP_IMPLEMENTATION_SUMMARY.md   # Implementation details
```

## MCP (Model Context Protocol)

The framework includes a complete MCP implementation for standardized tool integration:

### Creating Tools

```python
from sentientmilk_framework import mcp_tool, MCPParameter

@mcp_tool(
    name="my_tool",
    description="What my tool does",
    parameters=[
        MCPParameter(name="param", type="string", 
                    description="Parameter description", required=True)
    ]
)
def my_tool(param: str) -> str:
    return f"Result: {param}"

# Register and use
mcp_server.register_tool(my_tool._mcp_tool)
```

### Available Integrations

- **Internet Search**: Web search via LangSearch API
- **Voice**: Text-to-speech via ElevenLabs
- **Database**: Firebase Firestore integration
- **Custom Tools**: Easy to add your own

## Documentation

- **[MCP Usage Guide](MCP_USAGE.md)** - Complete MCP documentation
- **[Migration Guide](MIGRATION_GUIDE.md)** - Upgrading to MCP
- **[Implementation Summary](MCP_IMPLEMENTATION_SUMMARY.md)** - Technical details
- **[Example Usage](example_mcp_usage.py)** - Working code examples

## API Endpoints

The framework includes a Flask API server:

- `GET /` - Health check
- `GET /v1/models` - List available models
- `POST /v1/chat/completions` - OpenAI-compatible chat completions
- `POST /v1/audio/speech` - Text-to-speech (returns MP3 audio stream)
- `GET /v1/audio/voices` - List available voices with optional filtering

### Example Request

```bash
# Chat completion
curl -X POST http://localhost:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "milkchan",
    "messages": [
      {"role": "user", "content": "Hello!"}
    ],
    "stream": false
  }'

# Text-to-speech
curl -X POST http://localhost:8080/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input": "Hello from the API!"}' \
  --output speech.mp3
```

**Network Access:** See [Voice Network Guide](VOICE_NETWORK_GUIDE.md) for using voice features from other devices.

## Environment Variables

Create a `.env` file:

```env
API_KEY=your_llm_api_key
BASE_URL=https://your-llm-endpoint.com
WEB_SEARCH_KEY=your_search_api_key
ELEVENLABS_KEY=your_elevenlabs_key
PORT=8080
```

## Running the Server

```bash
python app.py
```

Server will start on `http://0.0.0.0:8080`

## Architecture

```
┌─────────────────────────────────────────┐
│         Your Application                │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│      SentientMilk Framework (LLM)       │
│  ┌───────────────────────────────────┐  │
│  │        MCP Server                 │  │
│  │  • Calculator Tool                │  │
│  │  • Weather Tool                   │  │
│  │  • Custom Tools                   │  │
│  └───────────────────────────────────┘  │
│  ┌───────────────────────────────────┐  │
│  │    Legacy Integrations            │  │
│  │  • Internet Search                │  │
│  │  • Voice (ElevenLabs)             │  │
│  └───────────────────────────────────┘  │
└──────────────┬──────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────┐
│     Language Model (Gemini, etc.)       │
└─────────────────────────────────────────┘
```

## Features in Detail

### Streaming Support

```python
response = ai_model.completion(
    model="gemini-2.5-flash",
    messages=[{"role": "user", "content": "Write a story"}],
    stream=True
)

for chunk in response:
    print(chunk['choices'][0]['delta']['content'], end='')
```

### Tool Calling

The framework automatically handles tool calling:
1. LLM decides to use a tool
2. Framework finds and executes the tool
3. Result is sent back to LLM
4. LLM generates final response with tool data

### Error Handling

Built-in error handling with proper logging:
- Tool execution errors
- API request failures
- Parameter validation
- Type checking

## Examples

See `example_mcp_usage.py` for complete examples including:
- Calculator tool
- Weather tool (mock)
- Web search integration
- Tool management
- Category filtering

## Contributing

Feel free to add new tools and integrations! The MCP system makes it easy:

1. Define your tool with parameters
2. Register it with the MCP server
3. The LLM can now use it automatically

## License

[Your License Here]

## Support

For questions and support, please refer to the documentation files or open an issue.

---

Built with ❤️ using Model Context Protocol
