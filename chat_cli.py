"""
Beautiful CLI Chat Application for SentientMilk Framework
Tests all features including streaming
"""
import os
import sys
import json
import time
from datetime import datetime
from typing import Optional, List

import requests
from dotenv import load_dotenv
from sentientmilk_framework import LLM, Settings

# Rich library for beautiful terminal UI
try:
    from rich.console import Console, Group
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.prompt import Prompt
    from rich.live import Live
    from rich.table import Table
    from rich.text import Text
    from rich import box
except ImportError:
    print("Installing required packages...")
    os.system("pip install rich")
    from rich.console import Console
    from rich.panel import Panel
    from rich.markdown import Markdown
    from rich.prompt import Prompt
    from rich.live import Live
    from rich.table import Table
    from rich.text import Text
    from rich import box

load_dotenv()

console = Console()

# Initialize conversation history
conversation_history: List[dict] = []


class ChatApp:
    def __init__(self):
        self.console = Console()
        self.api_key = os.getenv("API_KEY")
        self.base_url = os.getenv("BASE_URL")
        self.web_search_token = os.getenv("WEB_SEARCH_KEY")
        self.ai_model: Optional[LLM] = None
        self.streaming = True
        self.debug = False  # Debug streaming/logging
        self.render_mode = "markdown"  # or "plain"
        self.auto_speak = False  # Auto-speak AI responses
        self.model = "qwen/qwen3.5-122b-a10b"
        self._models_cache: Optional[List[dict]] = None
        
        self._live_segments = []
        self._tool_segments = {}
        self._current_assistant_index = None
        self._active_live = None
        self._initialize_ai()
    

    def _initialize_ai(self):
        """Initialize the AI model"""
        if not self.api_key:
            self.console.print("[red]Error: API_KEY not found in .env file[/red]")
            sys.exit(1)
        
        persona = """
        You are a helpful, capable general-purpose assistant.
        You are able to run agentic tasks, interacting with enviroment through recursive tool calls.
        Best practice is to execute task until it's completed and don't bother user.
        """

        self.ai_model = LLM(
            api_key=self.api_key,
            base_url=self.base_url,
            model=self.model,
            settings=Settings(persona=persona),
            tool_event_handler=self._handle_tool_event,
            web_search_token=self.web_search_token
        )

    def _add_segment(self, kind, **payload):
        segment = {"kind": kind, **payload}
        self._live_segments.append(segment)
        return len(self._live_segments) - 1

    def _handle_tool_event(self, event):
        timestamp = datetime.now().strftime("%H:%M:%S")
        call_id = event.get("call_id") or f"{event.get('tool_name','tool')}-{len(self._tool_segments)}"
        event_entry = {"time": timestamp, **event, "call_id": call_id}

        etype = event_entry.get("type")
        name = event_entry.get("tool_name", "tool")

        if etype == "tool_start":
            seg = {
                "kind": "tool",
                "call_id": call_id,
                "name": name,
                "status": "running",
                "arguments": event_entry.get("arguments", {}),
                "result": None,
                "error": None,
                "time": timestamp
            }
            self._tool_segments[call_id] = seg
            self._live_segments.append(seg)
        else:
            seg = self._tool_segments.get(call_id)
            if not seg:
                return
            if etype == "tool_end":
                seg["status"] = "success"
                seg["result"] = event_entry.get("result")
                seg["time"] = timestamp
            elif etype == "tool_error":
                seg["status"] = "error"
                seg["error"] = event_entry.get("error")
                seg["time"] = timestamp

        self._refresh_live_panel()

    def _render_segment(self, segment):
        kind = segment.get("kind")
        if kind == "user":
            return Panel(
                Text(segment.get("content", "")),
                title="[bold green]You[/bold green]",
                border_style="green",
                box=box.ROUNDED
            )
        if kind == "assistant":
            text = segment.get("content", "[dim]Thinking...[/dim]")
            body = Markdown(text) if self.render_mode == "markdown" else Text(text)
            return Panel(body, title="[bold blue]🤖 AI Assistant[/bold blue]", border_style="blue", box=box.ROUNDED)
        if kind == "tool":
            status = segment.get("status")
            name = segment.get("name")
            args = json.dumps(segment.get("arguments", {}), ensure_ascii=False)
            if status == "running":
                header = f"[cyan]↺ {name}[/cyan]"
                body = Text(f"Args: {args}")
                style = "cyan"
            elif status == "success":
                preview = json.dumps(segment.get("result"), ensure_ascii=False)
                if len(preview) > 120:
                    preview = preview[:117] + "..."
                header = f"[green]✓ {name}[/green]"
                body = Text(preview)
                style = "green"
            else:
                header = f"[red]⚠ {name}[/red]"
                body = Text(str(segment.get("error")))
                style = "red"
            return Panel(body, title=header, border_style=style, box=box.ROUNDED)
        return Panel(Text(json.dumps(segment, ensure_ascii=False)), title="Log", border_style="magenta")

    def _refresh_live_panel(self):
        if not self._active_live:
            return
        recent = self._live_segments[-8:]
        renderables = [self._render_segment(seg) for seg in recent]
        self._active_live.update(Group(*renderables), refresh=True)
    
    def show_banner(self):
        """Display welcome banner"""
        banner = """
╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║           🤖  SentientMilk Framework CLI Chat  🤖            ║
║                                                               ║
║                                                               ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝
        """
        self.console.print(banner, style="bold cyan")
        self.console.print("\n[yellow]Type your message or use commands:[/yellow]")
        self.console.print("  [cyan]/help[/cyan]     - Show all commands")
        self.console.print("  [cyan]/tools[/cyan]    - List available tools")
        self.console.print("  [cyan]/clear[/cyan]    - Clear conversation history")
        self.console.print("  [cyan]/stream[/cyan]   - Toggle streaming mode")
        self.console.print("  [cyan]/render <markdown|plain>[/cyan] - Set streaming render mode")
        self.console.print("  [cyan]/debug[/cyan]    - Toggle debug logs for streaming")
        self.console.print("  [cyan]/exit[/cyan]     - Exit the application")
        self.console.print()
    
    def show_help(self):
        """Show help information"""
        table = Table(title="Available Commands", box=box.ROUNDED)
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Description", style="white")
        
        commands = [
            ("/help", "Display this help message"),
            ("/tools", "List all available tools"),
            ("/clear", "Clear conversation history"),
            ("/history", "Show conversation history"),
            ("/stream on/off", "Toggle streaming mode"),
            ("/models", "Fetch available models from the API and pick one interactively"),
            ("/model <name>", "Change AI model"),
            ("/render <markdown|plain>", "Set streaming render mode (markdown is richer, plain is faster)"),
            ("/debug", "Toggle debug logs for streaming and responses"),
            ("/stats", "Show statistics"),
            ("/export", "Export conversation to file"),
            ("/exit or /quit", "Exit the application"),
        ]
        
        for cmd, desc in commands:
            table.add_row(cmd, desc)
        
        self.console.print(table)
    
    def show_tools(self):
        """Display available tools"""
        tools = self.ai_model._get_tools()
        if not tools:
            self.console.print("[yellow]No tools registered[/yellow]")
            return
        

        for tool in tools:
            table = Table(title=f"🔧 Tools", box=box.ROUNDED)
            table.add_column("Tool Name", style="cyan", no_wrap=True)
            table.add_column("Description", style="white")
            table.add_column("Parameters", style="yellow")
            
        for tool in tools:
            tool = tool['function']
            parameters = tool['parameters'].get('properties', {})
            required_parameters = tool['parameters'].get("required", None)
            
            table.add_row(tool.get("name"), tool.get("description"), Text.from_markup("".join(f"[green]{parameter}[/green]. Required? {'[cyan]True[/cyan]' if parameter in required_parameters else '[green]False[/green]'} | " for parameter in parameters.keys())[:-2]))
        
        self.console.print(table)
        self.console.print()
    
    def show_history(self):
        """Display conversation history"""
        if not conversation_history:
            self.console.print("[yellow]No conversation history[/yellow]")
            return
        
        self.console.print("\n[bold cyan]═══ Conversation History ═══[/bold cyan]\n")
        for msg in conversation_history:
            role = msg["role"]
            content = msg["content"]
            
            if role == "user":
                self.console.print(f"[bold green]You:[/bold green] {content}\n")
            elif role == "assistant":
                self.console.print(f"[bold blue]AI:[/bold blue] {content}\n")
    
    def show_stats(self):
        """Show statistics"""
        table = Table(title="📊 Statistics", box=box.ROUNDED)
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="green")
        
        stats = [
            ("Messages in history", str(len(conversation_history))),
            ("Streaming mode", "ON" if self.streaming else "OFF"),
            ("Auto-speak mode", "ON" if self.auto_speak else "OFF"),
            ("Debug mode", "ON" if self.debug else "OFF"),
            ("Render mode", self.render_mode.upper()),
            ("Current model", self.model),
        ]
        
        for metric, value in stats:
            table.add_row(metric, value)
        
        self.console.print(table)
    
    def export_conversation(self):
        """Export conversation to JSON file"""
        if not conversation_history:
            self.console.print("[yellow]No conversation to export[/yellow]")
            return
        
        filename = f"conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(conversation_history, f, indent=2, ensure_ascii=False)
        
        self.console.print(f"[green]✓ Conversation exported to {filename}[/green]")
    
    def handle_command(self, command: str) -> bool:
        """Handle slash commands. Returns True if should continue, False if should exit"""
        raw_command = command.strip()
        command = raw_command.lower()
        
        if command == "/exit" or command == "/quit":
            return False
        
        elif command == "/help":
            self.show_help()
        
        elif command == "/tools":
            self.show_tools()
        
        elif command == "/clear":
            conversation_history.clear()
            self.console.print("[green]✓ Conversation history cleared[/green]")
        
        elif command == "/history":
            self.show_history()
        
        elif command.startswith("/stream"):
            parts = raw_command.split()
            if len(parts) > 1:
                self.streaming = parts[1] == "on"
            else:
                self.streaming = not self.streaming
            
            status = "enabled" if self.streaming else "disabled"
            self.console.print(f"[green]✓ Streaming mode {status}[/green]")
        
        elif command == "/models":
            self.pick_model_via_tui()
        elif command.startswith("/model"):
            parts = raw_command.split(maxsplit=1)
            if len(parts) > 1:
                self.model = parts[1]
                if self.ai_model:
                    self.ai_model.model = self.model
                self.console.print(f"[green]✓ Model changed to {self.model}[/green]")
            else:
                self.console.print(f"[yellow]Current model: {self.model}[/yellow]")
        
        elif command.startswith("/render"):
            parts = raw_command.split(maxsplit=1)
            if len(parts) > 1 and parts[1] in ("markdown", "plain"):
                self.render_mode = parts[1]
                self.console.print(f"[green]✓ Render mode set to {self.render_mode}[/green]")
                if self.render_mode == "plain":
                    self.console.print("[dim]Tip: Plain mode streams faster with less flicker, Markdown will be applied in non-streaming replies or if you switch back.[/dim]")
            else:
                self.console.print(f"[yellow]Current render mode: {self.render_mode}. Usage: /render <markdown|plain>[/yellow]")

        elif command == "/stats":
            self.show_stats()
        
        elif command == "/export":
            self.export_conversation()

        elif command == "/debug":
            self.debug = not self.debug
            status = "enabled" if self.debug else "disabled"
            self.console.print(f"[green]✓ Debug mode {status}[/green]")
        
        else:
            self.console.print(f"[red]Unknown command: {command}[/red]")
            self.console.print("[yellow]Type /help for available commands[/yellow]")
        
        return True

    def _fetch_models(self) -> List[dict]:
        if not self.base_url:
            raise RuntimeError("BASE_URL is not configured.")

        url = f"{self.base_url.rstrip('/')}/models"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()

        payload = response.json()
        if isinstance(payload, list):
            raw_models = payload
        elif isinstance(payload, dict):
            raw_models = payload.get("data") or payload.get("models") or payload.get("items") or []
            if isinstance(raw_models, dict):
                raw_models = list(raw_models.values())
        else:
            raw_models = []

        normalized = []
        for item in raw_models:
            if isinstance(item, str):
                normalized.append({"id": item, "display_name": item})
                continue

            if not isinstance(item, dict):
                continue

            identifier = item.get("id") or item.get("name") or item.get("model")
            if not identifier:
                continue

            normalized.append({
                "id": identifier,
                "display_name": item.get("display_name") or item.get("title") or identifier,
                "context": item.get("context_length") or item.get("max_context_tokens") or item.get("context_tokens"),
                "owner": item.get("owned_by") or item.get("provider") or item.get("organization"),
                "capabilities": item.get("capabilities") or item.get("tags") or item.get("features"),
                "raw": item,
            })

        return normalized

    def _render_models_table(self, models: List[dict]):
        table = Table(
            title="[bold magenta]✨ Available Models[/bold magenta]",
            box=box.DOUBLE_EDGE,
            header_style="bold cyan",
            row_styles=["none", "dim"],
            show_lines=True,
        )
        table.add_column("#", justify="center", style="bold white")
        table.add_column("Model", style="bold green")
        table.add_column("Provider", style="cyan")
        table.add_column("Context", justify="right", style="yellow")
        table.add_column("Highlights", style="magenta")

        for idx, model in enumerate(models, start=1):
            badges: list[str] = []
            caps = model.get("capabilities")
            if isinstance(caps, dict):
                badges = [k for k, enabled in caps.items() if enabled]
            elif isinstance(caps, list):
                badges = [str(c) for c in caps]

            provider = model.get("owner") or "—"
            ctx = model.get("context") or "—"
            name = model.get("display_name") or model["id"]
            row_style = "bold green" if model["id"] == self.model else None

            table.add_row(
                f"{idx}",
                f"{name}\n[dim]{model['id']}[/dim]",
                provider,
                str(ctx),
                " • ".join(badges) if badges else "—",
                style=row_style,
            )

        self.console.print(table)

    def pick_model_via_tui(self):
        try:
            models = self._models_cache or self._fetch_models()
            self._models_cache = models
        except Exception as exc:
            self.console.print(f"[red]Failed to load models: {exc}[/red]")
            return

        if not models:
            self.console.print("[yellow]No models returned by the server.[/yellow]")
            return

        self.console.print(Panel(
            "Browse curated models straight from your endpoint. Type the number to switch instantly, or press Enter to keep the current model.",
            title="[bold cyan]Model Explorer[/bold cyan]",
            border_style="cyan",
            box=box.HEAVY,
        ))
        self._render_models_table(models)

        choices = [str(idx) for idx in range(1, len(models) + 1)]
        selection = Prompt.ask(
            "[bold green]Pick a model[/bold green] (Enter to cancel)",
            default="",
            show_default=False,
        )

        if not selection.strip():
            self.console.print("[dim]Model selection cancelled.[/dim]")
            return

        if selection not in choices:
            self.console.print("[red]Invalid selection.[/red]")
            return

        chosen = models[int(selection) - 1]
        self.model = chosen["id"]
        if self.ai_model:
            self.ai_model.model = self.model

        details = Text.assemble(
            ("Model", "bold"), (": ",), (chosen.get("display_name") or self.model, "green"), "\n",
            ("Identifier", "bold"), (": ",), (self.model, "cyan"), "\n",
            ("Provider", "bold"), (": ",), (chosen.get("owner") or "—", "magenta"),
        )
        self.console.print(
            Panel(
                details,
                title="[bold green]✓ Model updated[/bold green]",
                border_style="green",
                box=box.ROUNDED,
            )
        )
    
    def chat_streaming(self, user_message: str):
        """Handle streaming chat"""
        conversation_history.append({"role": "user", "content": user_message})
        self._add_segment("user", content=user_message)
        
        try:
            response_text = ""
            chunk_count = 0
            
            with Live(console=self.console, refresh_per_second=10) as live:
                self._active_live = live
                self._current_assistant_index = self._add_segment("assistant", content="")
                placeholder = Text.from_markup("[dim]Connecting to model...[/dim]\n")
                live.update(Panel(placeholder, title="[bold blue]🤖 AI Assistant[/bold blue]", border_style="blue", box=box.ROUNDED), refresh=True)
                start_time = time.time()
                first_chunk_time = None
                last_time = start_time
                
                for chunk in self.ai_model.completion(
                    messages=conversation_history,
                    stream=True
                ):
                    if self.debug:
                        # Minimal, non-intrusive debug line with timing
                        now = time.time()
                        try:
                            c = chunk.get('choices', [{}])[0]
                            delta = c.get('delta', {})
                            dbg_len = len(delta.get('content', '') or '')
                            finish = c.get('finish_reason', None)
                            dt_ms = int((now - last_time) * 1000)
                            live.console.print(f"[dim]chunk#{chunk_count+1} +{dt_ms}ms len={dbg_len} finish={finish}[/dim]")
                        except Exception:
                            live.console.print("[dim]chunk(received)[/dim]")
                        last_time = now

                    if 'choices' in chunk and len(chunk['choices']) > 0:
                        delta = chunk['choices'][0].get('delta', {})
                        content = delta.get('content', '')
                        
                        if content:
                            if first_chunk_time is None:
                                first_chunk_time = time.time()
                            response_text += content
                            if self._current_assistant_index is not None:
                                self._live_segments[self._current_assistant_index]["content"] = response_text
                            self._refresh_live_panel()
                        chunk_count += 1
            self._active_live = None
            self._current_assistant_index = None
            
            # Add final response to history
            if response_text:
                conversation_history.append({"role": "assistant", "content": response_text})
            
            if self.debug:
                end_time = time.time()
                total_ms = int((end_time - start_time) * 1000)
                ttfb_ms = int((first_chunk_time - start_time) * 1000) if first_chunk_time else None
                chars = len(response_text)
                cps = int(chars / (end_time - (first_chunk_time or start_time))) if (first_chunk_time and end_time > first_chunk_time) else 0
                self.console.print(f"[dim]summary: chunks={chunk_count} total={total_ms}ms ttfb={ttfb_ms if ttfb_ms is not None else 'n/a'}ms chars={chars} cps≈{cps}[/dim]")

            if not response_text:
                self.console.print("[yellow]No content received. Possible reasons: network timeout, model overload, or invalid API key/base URL. Try /stream off or check your .env.[/yellow]")
            elif chunk_count <= 1 and self.streaming:
                self.console.print("[dim]Note: Response arrived as a single chunk. Upstream may buffer or not support incremental streaming.[/dim]")
            
            self.console.print()  # Add spacing
            
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
    
    def chat_non_streaming(self, user_message: str):
        """Handle non-streaming chat"""
        conversation_history.append({"role": "user", "content": user_message})
        
        try:
            with self.console.status("[cyan]Thinking...[/cyan]", spinner="dots"):
                response = self.ai_model.completion(
                    messages=conversation_history,
                    stream=False
                )
            
            if isinstance(response, dict) and 'error' in response:
                self.console.print(f"[red]API Error: {response['error']}[/red]")
                self.console.print("[yellow]Tip: Check API_KEY, BASE_URL and internet connection. Try toggling /stream off.[/yellow]")
            elif 'choices' in response and len(response['choices']) > 0:
                response_text = response['choices'][0]['message']['content']
                conversation_history.append({"role": "assistant", "content": response_text})
                
                panel = Panel(
                    Markdown(response_text),
                    title="[bold blue]🤖 AI Assistant[/bold blue]",
                    border_style="blue",
                    box=box.ROUNDED
                )
                self.console.print(panel)
                
            else:
                self.console.print("[red]No response from AI[/red]")
                self.console.print("[yellow]Tip: The model returned an unexpected payload. Check server logs and configuration.[/yellow]")
        
        except Exception as e:
            self.console.print(f"[red]Error: {e}[/red]")
    
    def run(self):
        """Main chat loop"""
        self.show_banner()
        
        try:
            while True:
                # Get user input
                user_input = Prompt.ask("\n[bold green]You[/bold green]")
                
                if not user_input.strip():
                    continue
                
                # Handle commands
                if user_input.startswith("/"):
                    if not self.handle_command(user_input):
                        break
                    continue
                
                # Handle chat
                if self.streaming:
                    self.chat_streaming(user_input)
                else:
                    self.chat_non_streaming(user_input)
        
        except KeyboardInterrupt:
            self.console.print("\n\n[yellow]Interrupted by user[/yellow]")
        
        except Exception as e:
            self.console.print(f"\n[red]Fatal error: {e}[/red]")
        
        finally:
            self.console.print("\n[cyan]👋 Goodbye! Thanks for using SentientMilk CLI Chat![/cyan]\n")


def main():
    """Entry point"""
    app = ChatApp()
    app.run()


if __name__ == "__main__":
    main()
