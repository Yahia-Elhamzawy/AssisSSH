"""
Session Persistence Manager for AI Server Agent
Stores conversation history, turns, actions, and metadata on disk in JSON format.
"""
import os
import json
import time
from datetime import datetime
from typing import List, Dict, Any, Optional

SESSIONS_DIR = os.path.join(os.path.dirname(__file__), "sessions")


def ensure_sessions_dir():
    """Ensure the sessions directory exists."""
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def _get_session_path(session_id: str) -> str:
    """Get clean sanitized path for a session JSON file."""
    clean_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_")).strip()
    if not clean_id:
        clean_id = "default"
    return os.path.join(SESSIONS_DIR, f"{clean_id}.json")


def save_session(session_id: str, data: Dict[str, Any]) -> bool:
    """Save or update session data to disk."""
    ensure_sessions_dir()
    filepath = _get_session_path(session_id)
    try:
        now_iso = datetime.now().isoformat()
        if "created_at" not in data:
            data["created_at"] = now_iso
        data["updated_at"] = now_iso
        data["session_id"] = session_id

        # Atomic write with temp file
        temp_path = f"{filepath}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Replace atomically
        if os.path.exists(filepath):
            os.replace(temp_path, filepath)
        else:
            os.rename(temp_path, filepath)
        return True
    except Exception as e:
        print(f"[SessionManager] Error saving session {session_id}: {e}")
        return False


def load_session(session_id: str) -> Optional[Dict[str, Any]]:
    """Load session data from disk if it exists."""
    ensure_sessions_dir()
    filepath = _get_session_path(session_id)
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"[SessionManager] Error loading session {session_id}: {e}")
        return None


def list_sessions() -> List[Dict[str, Any]]:
    """List all saved sessions, sorted by last updated descending."""
    ensure_sessions_dir()
    sessions = []
    for filename in os.listdir(SESSIONS_DIR):
        if not filename.endswith(".json") or filename.endswith(".tmp"):
            continue
        filepath = os.path.join(SESSIONS_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
                sessions.append({
                    "session_id": data.get("session_id", filename.replace(".json", "")),
                    "title": data.get("title", "جلسة بدون عنوان"),
                    "created_at": data.get("created_at", ""),
                    "updated_at": data.get("updated_at", ""),
                    "turn_count": data.get("turn_count", len(data.get("turns", []))),
                    "action_count": data.get("action_count", 0),
                    "active_provider": data.get("active_provider", "gemini")
                })
        except Exception:
            continue

    # Sort by updated_at desc
    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions


def delete_session(session_id: str) -> bool:
    """Delete a session file from disk."""
    ensure_sessions_dir()
    filepath = _get_session_path(session_id)
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            return True
        except Exception as e:
            print(f"[SessionManager] Error deleting session {session_id}: {e}")
            return False
    return False


def create_new_session(session_id: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
    """Create a new fresh session and save it."""
    ensure_sessions_dir()
    if not session_id:
        session_id = f"session_{int(time.time())}"
    now_iso = datetime.now().isoformat()
    session_data = {
        "session_id": session_id,
        "title": title or f"جلسة جديدة #{session_id.split('_')[-1]}",
        "created_at": now_iso,
        "updated_at": now_iso,
        "turn_count": 0,
        "action_count": 0,
        "turns": [],
        "serialized_history": [],
        "active_provider": "gemini"
    }
    save_session(session_id, session_data)
    return session_data


def content_to_dict(content) -> Dict[str, Any]:
    """Serialize Google GenAI types.Content object into a JSON-serializable dict."""
    parts = []
    for p in (getattr(content, "parts", None) or []):
        if hasattr(p, "text") and p.text:
            parts.append({"type": "text", "text": p.text})
        elif hasattr(p, "function_call") and p.function_call:
            fc = p.function_call
            parts.append({
                "type": "function_call",
                "name": getattr(fc, "name", ""),
                "args": dict(fc.args) if getattr(fc, "args", None) else {}
            })
        elif hasattr(p, "function_response") and p.function_response:
            fr = p.function_response
            resp_data = getattr(fr, "response", {})
            parts.append({
                "type": "function_response",
                "name": getattr(fr, "name", ""),
                "response": dict(resp_data) if isinstance(resp_data, dict) else {"result": str(resp_data)}
            })
    return {"role": getattr(content, "role", "user"), "parts": parts}


def dict_to_content(data: Dict[str, Any]):
    """Deserialize dict back into Google GenAI types.Content."""
    from google.genai import types
    role = data.get("role", "user")
    parts = []
    for p in data.get("parts", []):
        ptype = p.get("type")
        if ptype == "text":
            parts.append(types.Part.from_text(text=p.get("text", "")))
        elif ptype == "function_call":
            parts.append(types.Part.from_function_call(name=p.get("name", ""), args=p.get("args", {})))
        elif ptype == "function_response":
            parts.append(types.Part.from_function_response(name=p.get("name", ""), response=p.get("response", {})))
    return types.Content(role=role, parts=parts)

