"""
Unified Multi-Provider LLM Engine for AI Server Agent
Supports Google Gemini, Groq, and OpenRouter/DeepSeek with automatic HTTP 429 fallback.
"""
import os
import sys
import json
import time
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from google.genai import types


@dataclass
class ToolCall:
    id: str
    name: str
    args: Dict[str, Any]


@dataclass
class UnifiedLLMResponse:
    text: str = ""
    function_calls: List[ToolCall] = field(default_factory=list)
    provider: str = "gemini"
    model: str = ""
    raw_content: Any = None


def get_openai_tools(enable_web_search: bool = False) -> List[Dict[str, Any]]:
    """Build tool definitions in OpenAI format for Groq / OpenRouter."""
    tools = [
        {
            "type": "function",
            "function": {
                "name": "execute_command",
                "description": "Execute a shell command on the remote Ubuntu server. Use for non-root commands.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The shell command to execute, e.g. 'docker ps', 'df -h', 'cat /var/log/syslog | tail -50'"
                        }
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "execute_sudo_command",
                "description": "Execute a shell command with sudo privileges. Do NOT include 'sudo' in the command.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Command to run with sudo, e.g. 'systemctl restart nginx', 'apt update'"
                        }
                    },
                    "required": ["command"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read the contents of a file on the remote server.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the file, e.g. '/etc/nginx/nginx.conf'"
                        }
                    },
                    "required": ["path"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write text content to a file on the server.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute path to the destination file"
                        },
                        "content": {
                            "type": "string",
                            "description": "The text content to write"
                        }
                    },
                    "required": ["path", "content"]
                }
            }
        },
        {
            "type": "function",
            "function": {
                "name": "list_directory",
                "description": "List files and directories at a given path with details.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Absolute directory path, e.g. '/var/log' or '/home/yy'"
                        }
                    },
                    "required": ["path"]
                }
            }
        }
    ]

    if enable_web_search:
        tools.append({
            "type": "function",
            "function": {
                "name": "search_web",
                "description": "Search the live web for error solutions, Ubuntu documentation, package names, configuration guides, and troubleshooting steps.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query, e.g. 'Ubuntu fix systemd service failed', 'docker compose port 80 in use'"
                        }
                    },
                    "required": ["query"]
                }
            }
        })

    return tools


def convert_history_to_openai(conversation_history: List[types.Content], system_prompt: str) -> List[Dict[str, Any]]:
    """Convert Google GenAI Content history into OpenAI-compatible message list."""
    openai_messages = [{"role": "system", "content": system_prompt}]

    for item in conversation_history:
        role = "assistant" if item.role == "model" else "user"
        parts = item.parts or []

        # Check for function responses (from user to assistant)
        func_responses = [p for p in parts if hasattr(p, "function_response") and p.function_response]
        if func_responses:
            for fr in func_responses:
                resp_obj = fr.function_response
                name = getattr(resp_obj, "name", "execute_command")
                response_data = getattr(resp_obj, "response", {})
                content_str = response_data.get("result", "") if isinstance(response_data, dict) else str(response_data)
                openai_messages.append({
                    "role": "tool",
                    "tool_call_id": f"call_{name}_{int(time.time()*1000)%100000}",
                    "name": name,
                    "content": content_str
                })
            continue

        # Check for function calls (from assistant)
        func_calls = [p for p in parts if hasattr(p, "function_call") and p.function_call]
        text_parts = [p.text for p in parts if hasattr(p, "text") and p.text]
        combined_text = "\n".join(text_parts) if text_parts else None

        if func_calls:
            tool_calls = []
            for i, fc in enumerate(func_calls):
                call_obj = fc.function_call
                name = getattr(call_obj, "name", "")
                args = getattr(call_obj, "args", {})
                if not isinstance(args, dict):
                    args = dict(args) if args else {}
                tool_calls.append({
                    "id": f"call_{name}_{i}_{int(time.time()*1000)%100000}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args, ensure_ascii=False)
                    }
                })
            openai_messages.append({
                "role": "assistant",
                "content": combined_text,
                "tool_calls": tool_calls
            })
        else:
            if combined_text:
                openai_messages.append({
                    "role": role,
                    "content": combined_text
                })

    return openai_messages


def is_rate_limit_error(exception: Exception) -> bool:
    """Check if exception represents HTTP 429 / Resource Exhausted / Rate Limit."""
    err_str = str(exception).lower()
    if "429" in err_str:
        return True
    if "resource_exhausted" in err_str or "resourceexhausted" in err_str:
        return True
    if "rate_limit" in err_str or "ratelimit" in err_str or "quota" in err_str:
        return True
    if isinstance(exception, urllib.error.HTTPError) and exception.code == 429:
        return True
    return False


class MultiProviderLLM:
    """
    Manages generation across Google Gemini, Groq, and OpenRouter/DeepSeek.
    Automatically handles 429 ResourceExhausted fallback.
    """

    def __init__(self, gemini_client, gemini_model: str = "gemini-3.5-flash-lite"):
        self.gemini_client = gemini_client
        self.gemini_model = gemini_model
        self.groq_key = os.getenv("GROQ_API_KEY", "").strip()
        self.groq_model = "qwen/qwen3.8-27b"
        self.openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.openrouter_model = "meta-llama/llama-3.3-70b-instruct"
        self.active_provider = "gemini"

    def generate(
        self,
        conversation_history: List[types.Content],
        system_prompt: str,
        gemini_tools_schema: Any,
        enable_web_search: bool = False,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None
    ) -> UnifiedLLMResponse:
        """
        Execute completion with automatic 429 fallback across Gemini -> Groq -> OpenRouter.
        """
        providers_order = ["gemini", "groq", "openrouter"]

        # If currently switched to Groq or OpenRouter due to earlier 429, prioritize active provider
        if self.active_provider != "gemini":
            providers_order = [self.active_provider] + [p for p in providers_order if p != self.active_provider]

        last_error = None

        for provider in providers_order:
            try:
                if provider == "gemini":
                    resp = self._call_gemini(conversation_history, system_prompt, gemini_tools_schema)
                    self.active_provider = "gemini"
                    return resp

                elif provider == "groq":
                    if not self.groq_key:
                        continue
                    resp = self._call_groq(conversation_history, system_prompt, enable_web_search)
                    self.active_provider = "groq"
                    return resp

                elif provider == "openrouter":
                    if not self.openrouter_key:
                        continue
                    resp = self._call_openrouter(conversation_history, system_prompt, enable_web_search)
                    self.active_provider = "openrouter"
                    return resp

            except Exception as e:
                last_error = e
                is_429 = is_rate_limit_error(e)

                # Determine next provider
                curr_idx = providers_order.index(provider)
                next_provider = providers_order[curr_idx + 1] if curr_idx + 1 < len(providers_order) else None

                if is_429 and next_provider:
                    provider_names = {
                        "gemini": "Google Gemini 3.5",
                        "groq": "Groq (Qwen 3.8 / 120B) ⚡",
                        "openrouter": "OpenRouter / DeepSeek 🌐"
                    }
                    switch_msg = f"⚠️ تم استهلاك كوتة {provider_names.get(provider, provider)} (429) — جاري المتابعة تلقائياً عبر {provider_names.get(next_provider, next_provider)}"
                    print(f"[MultiProviderLLM] {switch_msg}", file=sys.stderr)

                    if on_event:
                        on_event("provider_switch", {
                            "from": provider,
                            "to": next_provider,
                            "message": switch_msg,
                            "reason": "429_RATE_LIMIT"
                        })
                        on_event("thinking", {
                            "message": switch_msg
                        })

                    # Fallthrough to try next provider in loop
                    continue
                else:
                    # Non-429 error or no fallback left
                    raise e

        if last_error:
            raise last_error
        raise RuntimeError("No LLM provider available or configured.")

    def _call_gemini(
        self,
        conversation_history: List[types.Content],
        system_prompt: str,
        gemini_tools_schema: Any
    ) -> UnifiedLLMResponse:
        """Execute request via Google GenAI SDK."""
        tools_list = [gemini_tools_schema] if gemini_tools_schema else None
        config_kwargs = {
            "system_instruction": system_prompt,
            "temperature": 0.2,
        }
        if tools_list:
            config_kwargs["tools"] = tools_list
            config_kwargs["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)

        config = types.GenerateContentConfig(**config_kwargs)

        response = self.gemini_client.models.generate_content(
            model=self.gemini_model,
            contents=conversation_history,
            config=config
        )

        response_text = ""
        try:
            response_text = response.text or ""
        except (ValueError, AttributeError):
            if response.candidates and response.candidates[0].content and response.candidates[0].content.parts:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, "text") and part.text:
                        response_text += part.text

        tool_calls = []
        if response.function_calls:
            for call in response.function_calls:
                call_args = call.args
                if not isinstance(call_args, dict):
                    call_args = dict(call_args) if call_args else {}
                tool_calls.append(ToolCall(
                    id=f"gemini_{call.name}_{int(time.time()*1000)%100000}",
                    name=call.name,
                    args=call_args
                ))

        raw_content = response.candidates[0].content if response.candidates else None

        return UnifiedLLMResponse(
            text=response_text,
            function_calls=tool_calls,
            provider="gemini",
            model=self.gemini_model,
            raw_content=raw_content
        )

    def _call_groq(
        self,
        conversation_history: List[types.Content],
        system_prompt: str,
        enable_web_search: bool = False
    ) -> UnifiedLLMResponse:
        """Execute request via Groq OpenAI-compatible API."""
        openai_messages = convert_history_to_openai(conversation_history, system_prompt)
        tools = get_openai_tools(enable_web_search=enable_web_search)

        payload = {
            "model": self.groq_model,
            "messages": openai_messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2
        }

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.groq_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AI-DevOps-Studio/3.5"
            }
        )

        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # If qwen model fails, try openai/gpt-oss-120b as backup
            if e.code == 404:
                payload["model"] = "openai/gpt-oss-120b"
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Authorization": f"Bearer {self.groq_key}",
                        "Content-Type": "application/json",
                        "User-Agent": "Mozilla/5.0"
                    }
                )
                with urllib.request.urlopen(req, timeout=45) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            else:
                raise e

        choice = data["choices"][0]
        msg = choice.get("message", {})
        response_text = msg.get("content") or ""

        tool_calls = []
        raw_tc_list = msg.get("tool_calls") or []
        for tc in raw_tc_list:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                parsed_args = {"command": raw_args}

            tool_calls.append(ToolCall(
                id=tc.get("id", f"groq_{name}_{int(time.time()*1000)%100000}"),
                name=name,
                args=parsed_args
            ))

        # Convert to a compatible types.Content structure so agent can append to history
        parts = []
        if response_text:
            parts.append(types.Part.from_text(text=response_text))
        for tc in tool_calls:
            parts.append(types.Part.from_function_call(name=tc.name, args=tc.args))

        raw_content = types.Content(role="model", parts=parts) if parts else None

        return UnifiedLLMResponse(
            text=response_text,
            function_calls=tool_calls,
            provider="groq",
            model=self.groq_model,
            raw_content=raw_content
        )

    def _call_openrouter(
        self,
        conversation_history: List[types.Content],
        system_prompt: str,
        enable_web_search: bool = False
    ) -> UnifiedLLMResponse:
        """Execute request via OpenRouter or DeepSeek."""
        openai_messages = convert_history_to_openai(conversation_history, system_prompt)
        tools = get_openai_tools(enable_web_search=enable_web_search)

        is_deepseek_key = not self.openrouter_key.startswith("sk-or-")
        endpoint = "https://api.deepseek.com/chat/completions" if is_deepseek_key else "https://openrouter.ai/api/v1/chat/completions"
        model_name = "deepseek-chat" if is_deepseek_key else self.openrouter_model

        payload = {
            "model": model_name,
            "messages": openai_messages,
            "tools": tools,
            "tool_choice": "auto",
            "temperature": 0.2
        }

        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.openrouter_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0"
            }
        )

        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choice = data["choices"][0]
        msg = choice.get("message", {})
        response_text = msg.get("content") or ""

        tool_calls = []
        raw_tc_list = msg.get("tool_calls") or []
        for tc in raw_tc_list:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            raw_args = fn.get("arguments", "{}")
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except Exception:
                parsed_args = {"command": raw_args}

            tool_calls.append(ToolCall(
                id=tc.get("id", f"openrouter_{name}"),
                name=name,
                args=parsed_args
            ))

        parts = []
        if response_text:
            parts.append(types.Part.from_text(text=response_text))
        for tc in tool_calls:
            parts.append(types.Part.from_function_call(name=tc.name, args=tc.args))

        raw_content = types.Content(role="model", parts=parts) if parts else None

        return UnifiedLLMResponse(
            text=response_text,
            function_calls=tool_calls,
            provider="openrouter",
            model=model_name,
            raw_content=raw_content
        )
