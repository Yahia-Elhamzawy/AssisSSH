"""
AI Server Agent — الـ AI اللي بيحل مشاكل السيرفر
Uses Google Gemini API with manual function calling for a goal-oriented agent loop.
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import os
import json
import queue
import threading
from google import genai
from datetime import datetime
from google.genai import types
from dotenv import load_dotenv

from llm_providers import MultiProviderLLM, UnifiedLLMResponse, ToolCall
import session_manager
from session_manager import content_to_dict, dict_to_content

load_dotenv()

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), ".settings.json")


def load_settings() -> dict:
    """Load persistent application settings (e.g. max_steps)."""
    default_settings = {"max_steps": 20}
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "max_steps" in data:
                    default_settings["max_steps"] = max(5, min(int(data["max_steps"]), 100))
        except Exception:
            pass
    return default_settings


def save_settings(new_settings: dict) -> bool:
    """Save persistent application settings."""
    try:
        current = load_settings()
        current.update(new_settings)
        if "max_steps" in current:
            current["max_steps"] = max(5, min(int(current["max_steps"]), 100))
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2, ensure_ascii=False)
        return True
    except Exception:
        return False


# System prompt for the AI agent (with dynamic {max_steps})
SYSTEM_PROMPT = """You are an expert Linux/Ubuntu server administrator AI agent.
You are connected to a real Ubuntu server via SSH and can execute commands directly.

Your job is to ACHIEVE THE GOAL the user gives you. You are goal-oriented:
- If a command fails, analyze the error and try a different approach
- Don't give up after one failure — keep trying until you solve the problem
- Think step by step: first diagnose, then plan, then execute
- After making changes, verify they worked

Available tools:
- execute_command: Run any shell command on the server
- execute_sudo_command: Run a command with sudo privileges (for things that need root)
- read_file: Read the contents of a file on the server
- write_file: Write content to a file on the server
- list_directory: List files and directories at a given path
- search_web: Search the live web/internet for error solutions, Ubuntu documentation, package names, configuration guides, and troubleshooting steps (available when web search is enabled)

Guidelines:
- Start by gathering information (check status, read logs, etc.)
- Explain what you're doing and why at each step
- If a command fails with an unfamiliar error or package problem, and search_web is available, use search_web to find the exact fix or correct package/command
- Be careful with destructive commands (rm, format, etc.)
- For Docker: you can check containers, images, logs, compose files, etc.
- For services: use systemctl to check/manage services
- Always verify your changes worked after making them
- Keep your responses concise but informative
- Respond in the same language the user uses (Arabic or English)
- When responding in Arabic, provide clean, structured bullet points for the final summary so it reads naturally.
- Maximum {max_steps} steps per task to achieve the goal and prevent infinite loops
"""


def _build_tools_schema(enable_web_search: bool = False):
    """Build the function declarations for the AI tools."""
    execute_command = types.FunctionDeclaration(
        name="execute_command",
        description="Execute a shell command on the remote server. Use this for any command that doesn't need root privileges.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "command": types.Schema(
                    type=types.Type.STRING,
                    description="The shell command to execute. Examples: 'docker ps', 'df -h', 'cat /var/log/syslog | tail -50'"
                )
            },
            required=["command"]
        )
    )

    execute_sudo_command = types.FunctionDeclaration(
        name="execute_sudo_command",
        description="Execute a shell command with sudo (root) privileges. Use this for commands that require elevated permissions like installing packages, restarting services, editing system config files.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "command": types.Schema(
                    type=types.Type.STRING,
                    description="The command to execute with sudo. Do NOT include 'sudo' in the command itself. Examples: 'systemctl restart nginx', 'apt update', 'docker restart my_container'"
                )
            },
            required=["command"]
        )
    )

    read_file = types.FunctionDeclaration(
        name="read_file",
        description="Read the contents of a file on the server. Useful for checking config files, logs, etc.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "path": types.Schema(
                    type=types.Type.STRING,
                    description="Absolute path to the file to read. Example: '/etc/nginx/nginx.conf'"
                )
            },
            required=["path"]
        )
    )

    write_file = types.FunctionDeclaration(
        name="write_file",
        description="Write content to a file on the server. Use with caution. For system files, this will use sudo automatically.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "path": types.Schema(
                    type=types.Type.STRING,
                    description="Absolute path to the file to write"
                ),
                "content": types.Schema(
                    type=types.Type.STRING,
                    description="The content to write to the file"
                )
            },
            required=["path", "content"]
        )
    )

    list_directory = types.FunctionDeclaration(
        name="list_directory",
        description="List files and directories at the given path with details (permissions, size, date).",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "path": types.Schema(
                    type=types.Type.STRING,
                    description="Absolute path to the directory to list. Example: '/var/log'"
                )
            },
            required=["path"]
        )
    )

    tools_list = [execute_command, execute_sudo_command, read_file, write_file, list_directory]

    if enable_web_search:
        search_web = types.FunctionDeclaration(
            name="search_web",
            description="Search the live internet for Linux solutions, Ubuntu package fixes, Docker errors, config guides, or documentation. Use this whenever you encounter unknown errors, need the latest commands, or need to verify package installation steps.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="The search query to look up on the web. Example: 'Ubuntu fix systemd service failed with result exit-code', 'docker compose port 80 already in use'"
                    )
                },
                required=["query"]
            )
        )
        tools_list.append(search_web)

    return types.Tool(function_declarations=tools_list)


class ServerAgent:
    """AI Agent that manages a server through SSH using Gemini AI."""

    def __init__(self, ssh_manager, session_id: str = "default", max_steps: int = None):
        """
        Initialize the agent.

        Args:
            ssh_manager: An SSHManager instance (already connected)
            session_id: Identifier for this agent session to maintain conversation memory
            max_steps: Maximum number of steps per task (defaults to 20 or saved settings)
        """
        self.ssh = ssh_manager
        self.session_id = session_id
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found in .env file")

        self.client = genai.Client(api_key=api_key)
        self.model = "gemini-3.5-flash-lite"
        self.llm = MultiProviderLLM(self.client, gemini_model=self.model)
        self.tools = _build_tools_schema()
        self.max_steps = max(5, min(int(max_steps), 100)) if max_steps is not None else load_settings().get("max_steps", 20)
        self._stop_flag = False
        self.event_queue = queue.Queue()
        self.conversation_history = []
        self.session_title = ""
        self.turns_log = []
        self.total_action_count = 0

        # Load session state from disk if exists
        self._load_from_disk()

    def _load_from_disk(self):
        """Restore previous session turns and history from disk if present."""
        saved = session_manager.load_session(self.session_id)
        if saved:
            self.session_title = saved.get("title", "")
            self.turns_log = saved.get("turns", [])
            self.total_action_count = saved.get("action_count", 0)
            raw_hist = saved.get("serialized_history", [])
            try:
                self.conversation_history = [dict_to_content(d) for d in raw_hist]
            except Exception as e:
                print(f"[ServerAgent] History reconstruction error for {self.session_id}: {e}")
            self.llm.active_provider = saved.get("active_provider", "gemini")

    def _save_to_disk(self):
        """Persist current session to disk."""
        if not self.session_title and self.turns_log:
            first_prompt = self.turns_log[0].get("user_prompt", "")
            self.session_title = first_prompt[:45] + ("..." if len(first_prompt) > 45 else "")
        elif not self.session_title:
            self.session_title = f"جلسة #{self.session_id.split('_')[-1]}"

        try:
            serialized_history = [content_to_dict(c) for c in self.conversation_history]
        except Exception:
            serialized_history = []

        data = {
            "session_id": self.session_id,
            "title": self.session_title,
            "turn_count": self.get_turn_count(),
            "action_count": self.total_action_count,
            "max_steps": self.max_steps,
            "turns": self.turns_log,
            "serialized_history": serialized_history,
            "active_provider": self.llm.active_provider
        }
        session_manager.save_session(self.session_id, data)

    def reset_session(self):
        """Clear conversation history for a fresh start and update disk."""
        self.conversation_history = []
        self.turns_log = []
        self.total_action_count = 0
        self._stop_flag = False
        self._save_to_disk()

    def get_turn_count(self) -> int:
        """Count how many user goals have been processed in this session."""
        return len([c for c in self.conversation_history if c.role == "user" and not any(
            hasattr(p, "function_response") and p.function_response for p in (c.parts or [])
        )])

    def _trim_history(self, max_messages: int = 30):
        """Keep the conversation history within reasonable bounds while preserving turn integrity."""
        if len(self.conversation_history) <= max_messages:
            return

        slice_idx = len(self.conversation_history) - max_messages
        while slice_idx < len(self.conversation_history):
            content = self.conversation_history[slice_idx]
            if content.role == "user":
                has_function_response = any(
                    hasattr(part, "function_response") and part.function_response
                    for part in (content.parts or [])
                )
                if not has_function_response:
                    break
            slice_idx += 1

        if slice_idx < len(self.conversation_history):
            self.conversation_history = self.conversation_history[slice_idx:]

    def stop(self):
        """Signal the agent to stop."""
        self._stop_flag = True

    def _emit(self, event_type: str, data: dict):
        """Push an event to the queue for SSE streaming."""
        self.event_queue.put({"type": event_type, "data": data})

    def _execute_tool(self, function_name: str, args: dict) -> str:
        """
        Execute a tool call from the AI and return the result.

        Args:
            function_name: Name of the function to call
            args: Arguments for the function

        Returns:
            String result of the tool execution
        """
        username = self.ssh.username or "user"
        hostname = self.ssh.hostname or "server"

        if function_name == "execute_command":
            command = args.get("command", "")
            self._emit("command", {
                "command": command,
                "sudo": False,
                "username": username,
                "hostname": hostname,
                "display_path": self.ssh.get_display_path()
            })
            result = self.ssh.execute_command(command)
            
            # Text returned to AI brain for reasoning
            ai_output = ""
            if result["stdout"]:
                ai_output += result["stdout"]
            if result["stderr"]:
                ai_output += ("\n" if ai_output else "") + f"STDERR: {result['stderr']}"
            ai_output += f"\n[Exit Code: {result['exit_code']}]"
            
            # Clean data emitted to the real-time UI terminal
            self._emit("output", {
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "exit_code": result["exit_code"],
                "command": command,
                "cwd": result.get("cwd", self.ssh.cwd),
                "display_path": result.get("display_path", self.ssh.get_display_path())
            })
            return ai_output

        elif function_name == "execute_sudo_command":
            command = args.get("command", "")
            self._emit("command", {
                "command": command,
                "sudo": True,
                "username": username,
                "hostname": hostname,
                "display_path": self.ssh.get_display_path()
            })
            result = self.ssh.execute_sudo_command(command)
            
            ai_output = ""
            if result["stdout"]:
                ai_output += result["stdout"]
            if result["stderr"]:
                ai_output += ("\n" if ai_output else "") + f"STDERR: {result['stderr']}"
            ai_output += f"\n[Exit Code: {result['exit_code']}]"
            
            self._emit("output", {
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "exit_code": result["exit_code"],
                "command": f"sudo {command}",
                "cwd": result.get("cwd", self.ssh.cwd),
                "display_path": result.get("display_path", self.ssh.get_display_path())
            })
            return ai_output

        elif function_name == "read_file":
            path = args.get("path", "")
            self._emit("command", {
                "command": f"cat {path}",
                "sudo": False,
                "username": username,
                "hostname": hostname,
                "display_path": self.ssh.get_display_path()
            })
            result = self.ssh.execute_command(f"cat {path}")
            if not result["success"]:
                result = self.ssh.execute_sudo_command(f"cat {path}")
                
            ai_output = result["stdout"] if result["success"] else f"Error reading file: {result['stderr']}"
            self._emit("output", {
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "exit_code": result["exit_code"],
                "command": f"cat {path}",
                "cwd": result.get("cwd", self.ssh.cwd),
                "display_path": result.get("display_path", self.ssh.get_display_path())
            })
            return ai_output

        elif function_name == "write_file":
            path = args.get("path", "")
            content = args.get("content", "")
            escaped = content.replace("'", "'\\''")
            cmd = f"cat << 'AGENT_EOF' > {path}\n{content}\nAGENT_EOF"
            self._emit("command", {
                "command": f"cat << 'EOF' > {path}",
                "sudo": False,
                "username": username,
                "hostname": hostname,
                "display_path": self.ssh.get_display_path()
            })
            result = self.ssh.execute_command(cmd)
            if not result["success"]:
                cmd = f"cat << 'AGENT_EOF' | sudo tee {path} > /dev/null\n{content}\nAGENT_EOF"
                result = self.ssh.execute_sudo_command(f"tee {path} > /dev/null << 'AGENT_EOF'\n{content}\nAGENT_EOF")
                
            ai_output = f"File written successfully: {path}" if result["success"] else f"Error writing file: {result['stderr']}"
            self._emit("output", {
                "stdout": f"File written: {path}" if result["success"] else "",
                "stderr": result["stderr"] if not result["success"] else "",
                "exit_code": result["exit_code"],
                "command": f"write {path}",
                "cwd": result.get("cwd", self.ssh.cwd),
                "display_path": result.get("display_path", self.ssh.get_display_path())
            })
            return ai_output

        elif function_name == "list_directory":
            path = args.get("path", "/")
            self._emit("command", {
                "command": f"ls -la {path}",
                "sudo": False,
                "username": username,
                "hostname": hostname,
                "display_path": self.ssh.get_display_path()
            })
            result = self.ssh.execute_command(f"ls -la {path}")
            ai_output = result["stdout"] if result["success"] else f"Error listing directory: {result['stderr']}"
            self._emit("output", {
                "stdout": result["stdout"],
                "stderr": result["stderr"],
                "exit_code": result["exit_code"],
                "command": f"ls -la {path}",
                "cwd": result.get("cwd", self.ssh.cwd),
                "display_path": result.get("display_path", self.ssh.get_display_path())
            })
            return ai_output

        elif function_name == "search_web":
            query = args.get("query", "")
            return self._search_web(query)

        else:
            return f"Unknown tool: {function_name}"

    def _search_web(self, query: str) -> str:
        """Search the live web for error solutions, packages, or documentation using ddgs."""
        clean_query = query.strip()
        self._emit("action", {
            "tool": "search_web",
            "description": f"🌐 البحث في الويب عن: {clean_query}",
            "args": {"query": clean_query}
        })
        self._emit("search", {
            "query": clean_query,
            "status": "searching"
        })

        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                results = list(ddgs.text(clean_query, max_results=4))

            if not results:
                self._emit("search", {"query": clean_query, "status": "empty", "count": 0})
                return f"No search results found on the web for: '{clean_query}'"

            formatted_parts = []
            results_payload = []
            for i, r in enumerate(results, 1):
                title = r.get("title", "Untitled")
                snippet = r.get("body", "")
                link = r.get("href", "")
                formatted_parts.append(f"[{i}] {title}\nURL: {link}\nDetails: {snippet}")
                results_payload.append({"title": title, "url": link, "snippet": snippet})

            self._emit("search", {
                "query": clean_query,
                "status": "done",
                "count": len(results),
                "results": results_payload
            })
            return f"Live Web Search Results for '{clean_query}':\n" + "\n---\n".join(formatted_parts)
        except Exception as e:
            err_msg = f"Web search encountered an error: {str(e)}"
            self._emit("search", {"query": clean_query, "status": "error", "error": str(e)})
            return err_msg

    def solve(self, goal: str, enable_web_search: bool = False, max_steps: int = None):
        """
        Main agent loop — work towards solving the given goal in the current session.

        Args:
            goal: The user's goal/problem description
            enable_web_search: Whether to equip the agent with live web search capability
            max_steps: Optional maximum steps override for this task
        """
        self._stop_flag = False
        turn_num = self.get_turn_count() + 1

        if max_steps is not None:
            self.max_steps = max(5, min(int(max_steps), 100))
        
        # Trim history if needed before adding new turn
        self._trim_history()

        search_note = " (🌐 Web Search Enabled)" if enable_web_search else ""
        is_new_session = len(self.conversation_history) == 0
        if is_new_session:
            self._emit("status", {"message": f"🎯 Goal (Turn 1): {goal}{search_note}", "turn": 1, "is_new": True})
            user_prompt = f"Goal: {goal}\n\nStart by understanding the current state of the server, then work towards achieving this goal. Think step by step."
        else:
            self._emit("status", {"message": f"🎯 Goal (Turn {turn_num}): {goal}{search_note}", "turn": turn_num, "is_new": False})
            user_prompt = f"Follow-up Goal / Instruction: {goal}\n\nYou must remember and maintain the context of what we previously checked, ran, and discovered in this session. Continue directly towards achieving this new goal."

        self.conversation_history.append(
            types.Content(role="user", parts=[
                types.Part.from_text(text=user_prompt)
            ])
        )

        self._emit("thinking", {"message": "Analyzing the request in the context of the current session..."})

        # Dynamically build tools schema with or without web search
        active_tools = _build_tools_schema(enable_web_search=enable_web_search)

        system_instruction = SYSTEM_PROMPT.format(max_steps=self.max_steps)

        turn_thoughts = []
        turn_actions = []

        step = 0
        while step < self.max_steps and not self._stop_flag:
            step += 1
            self._emit("status", {"message": f"Step {step}/{self.max_steps}", "step": step, "turn": turn_num, "provider": self.llm.active_provider})

            try:
                llm_response = self.llm.generate(
                    conversation_history=self.conversation_history,
                    system_prompt=system_instruction,
                    gemini_tools_schema=active_tools,
                    enable_web_search=enable_web_search,
                    on_event=self._emit
                )
            except Exception as e:
                self._emit("error", {"message": f"AI Engine Error ({self.llm.active_provider}): {str(e)}"})
                break

            response_text = llm_response.text or ""
            if response_text:
                turn_thoughts.append(response_text)
                self._emit("thinking", {"message": response_text, "provider": llm_response.provider})

            # Check if the model wants to call functions
            if llm_response.function_calls:
                if llm_response.raw_content:
                    self.conversation_history.append(llm_response.raw_content)

                # Execute each function call
                function_response_parts = []
                for call in llm_response.function_calls:
                    if self._stop_flag:
                        break

                    self.total_action_count += 1
                    result = self._execute_tool(call.name, call.args)
                    turn_actions.append({
                        "tool": call.name,
                        "args": call.args,
                        "result": str(result)[:300]
                    })
                    function_response_parts.append(
                        types.Part.from_function_response(
                            name=call.name,
                            response={"result": result}
                        )
                    )

                # Add function results to session conversation
                self.conversation_history.append(types.Content(
                    role="user",
                    parts=function_response_parts
                ))

            else:
                # No function calls — the AI is done
                if llm_response.raw_content:
                    self.conversation_history.append(llm_response.raw_content)

                final_msg = response_text or "Task completed."
                self._emit("done", {
                    "message": final_msg,
                    "steps": step,
                    "turn": turn_num,
                    "provider": llm_response.provider
                })

                # Save completed turn to persistent disk log
                self.turns_log.append({
                    "turn": turn_num,
                    "user_prompt": goal,
                    "thoughts": turn_thoughts,
                    "actions": turn_actions,
                    "assistant_response": final_msg,
                    "provider": llm_response.provider,
                    "timestamp": datetime.now().isoformat()
                })
                self._save_to_disk()
                break
        else:
            if self._stop_flag:
                final_msg = "⏹️ Agent stopped by user."
            else:
                final_msg = f"⚠️ Reached maximum steps ({self.max_steps}). The task may not be fully completed."

            self._emit("done", {
                "message": final_msg,
                "steps": step,
                "turn": turn_num,
                "provider": self.llm.active_provider
            })

            self.turns_log.append({
                "turn": turn_num,
                "user_prompt": goal,
                "thoughts": turn_thoughts,
                "actions": turn_actions,
                "assistant_response": final_msg,
                "provider": self.llm.active_provider,
                "timestamp": datetime.now().isoformat()
            })
            self._save_to_disk()

        # Signal end of stream
        self._emit("end", {"turn": turn_num, "provider": self.llm.active_provider})

    def run_in_background(self, goal: str, enable_web_search: bool = False, max_steps: int = None) -> threading.Thread:
        """
        Start the agent loop in a background thread.

        Args:
            goal: The user's goal
            enable_web_search: Whether live web search is enabled
            max_steps: Optional maximum steps limit

        Returns:
            The running thread
        """
        thread = threading.Thread(target=self.solve, args=(goal, enable_web_search, max_steps), daemon=True)
        thread.start()
        return thread


# -------------------------------------------------------------
# Global Multi-Session Store
# -------------------------------------------------------------
_session_store = {}

def get_or_create_agent_session(session_id: str, ssh_manager, max_steps: int = None) -> ServerAgent:
    """Retrieve an existing agent session or create a new one to maintain context."""
    effective_steps = max(5, min(int(max_steps), 100)) if max_steps is not None else load_settings().get("max_steps", 20)
    if session_id not in _session_store:
        _session_store[session_id] = ServerAgent(ssh_manager, session_id=session_id, max_steps=effective_steps)
    else:
        # Update ssh manager reference to ensure active connection
        _session_store[session_id].ssh = ssh_manager
        # Reset stop flag and re-initialize event queue for the new run
        _session_store[session_id]._stop_flag = False
        _session_store[session_id].event_queue = queue.Queue()
        _session_store[session_id].max_steps = effective_steps
    return _session_store[session_id]

def reset_session_by_id(session_id: str) -> bool:
    """Clear memory for a given session."""
    if session_id in _session_store:
        _session_store[session_id].reset_session()
        return True
    return False

def get_session_info(session_id: str) -> dict:
    """Get statistics about a session."""
    if session_id in _session_store:
        agent = _session_store[session_id]
        return {
            "session_id": session_id,
            "turns": agent.get_turn_count(),
            "messages_count": len(agent.conversation_history),
            "is_active": True,
            "active_provider": agent.llm.active_provider
        }
    data = session_manager.load_session(session_id)
    if data:
        return {
            "session_id": session_id,
            "turns": data.get("turn_count", 0),
            "messages_count": len(data.get("turns", [])),
            "is_active": False,
            "active_provider": data.get("active_provider", "gemini")
        }
    return {
        "session_id": session_id,
        "turns": 0,
        "messages_count": 0,
        "is_active": False,
        "active_provider": "gemini"
    }


def delete_session_by_id(session_id: str) -> bool:
    """Delete a session from memory and disk."""
    if session_id in _session_store:
        del _session_store[session_id]
    return session_manager.delete_session(session_id)


def list_all_sessions() -> list:
    """Return all persisted sessions with summaries."""
    return session_manager.list_sessions()


def get_full_session_data(session_id: str) -> dict:
    """Return detailed session data including turns and history."""
    if session_id in _session_store:
        agent = _session_store[session_id]
        agent._save_to_disk()
    data = session_manager.load_session(session_id)
    if not data:
        data = session_manager.create_new_session(session_id)
    return data

