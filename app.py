"""
AI Server Agent — Flask Web Application
واجهة ويب للتحكم في الـ AI Agent اللي بيدير السيرفر
"""
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
import os
import json
import queue
from flask import Flask, render_template, request, jsonify, Response
from ssh_manager import SSHManager
from agent import (
    ServerAgent, get_or_create_agent_session, reset_session_by_id, get_session_info,
    load_settings, save_settings, delete_session_by_id, list_all_sessions, get_full_session_data
)
from telegram_bot import start_bot_background, save_ssh_credentials

app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Global state
ssh = SSHManager()
current_agent = None


@app.route("/")
def index():
    """Serve the main page."""
    return render_template("index.html")


@app.after_request
def add_header(response):
    """Ensure browsers do not cache templates or static scripts in local development."""
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@app.route("/api/connect", methods=["POST"])
def connect():
    """Connect to the SSH server."""
    global ssh
    data = request.json

    hostname = data.get("hostname", "").strip()
    username = data.get("username", "").strip()
    password = data.get("password", "")
    sudo_password = data.get("sudo_password", "")
    port = int(data.get("port", 22))

    if not hostname or not username or not password:
        return jsonify({"success": False, "message": "Hostname, username, and password are required"}), 400

    # Disconnect existing connection if any
    if ssh.is_connected():
        ssh.disconnect()

    result = ssh.connect(
        hostname=hostname,
        username=username,
        password=password,
        port=port,
        sudo_password=sudo_password if sudo_password else None
    )

    if result["success"]:
        save_ssh_credentials(hostname, username, password, sudo_password, port)

    return jsonify(result)


@app.route("/api/disconnect", methods=["POST"])
def disconnect():
    """Disconnect from the SSH server."""
    global ssh, current_agent
    if current_agent:
        current_agent.stop()
        current_agent = None
    ssh.disconnect()
    return jsonify({"success": True, "message": "Disconnected"})


@app.route("/api/status", methods=["GET"])
def status():
    """Get current connection status."""
    return jsonify({
        "connected": ssh.is_connected(),
        "hostname": ssh.hostname,
        "username": ssh.username,
        "cwd": ssh.cwd,
        "display_path": ssh.get_display_path()
    })


@app.route("/api/solve")
def solve():
    """
    Start the AI agent to solve a goal within a persistent session. Returns SSE stream.

    Query params:
        goal: The goal/problem to solve
        session_id: Optional session ID (default: web_default)
        web_search: Optional boolean (true/false) to enable live internet search
    """
    global current_agent

    goal = request.args.get("goal", "").strip()
    session_id = request.args.get("session_id", "web_default").strip()
    web_search = request.args.get("web_search", "false").lower() in ("true", "1", "yes")

    # Read optional max_steps override, otherwise use saved settings (default 20)
    max_steps_param = request.args.get("max_steps")
    effective_max_steps = None
    if max_steps_param:
        try:
            effective_max_steps = max(5, min(int(max_steps_param), 100))
        except ValueError:
            pass
    if not effective_max_steps:
        effective_max_steps = load_settings().get("max_steps", 20)

    if not goal:
        return jsonify({"success": False, "message": "Goal is required"}), 400

    if not ssh.is_connected():
        return jsonify({"success": False, "message": "Not connected to any server"}), 400

    # Stop previous agent loop if running
    if current_agent:
        current_agent.stop()

    # Retrieve or create session agent
    try:
        current_agent = get_or_create_agent_session(session_id, ssh, max_steps=effective_max_steps)
    except ValueError as e:
        return jsonify({"success": False, "message": str(e)}), 500

    # Start agent in background with web search and max_steps configuration
    current_agent.run_in_background(goal, enable_web_search=web_search, max_steps=effective_max_steps)

    def event_stream():
        """Generator that yields SSE events from the agent."""
        while True:
            try:
                event = current_agent.event_queue.get(timeout=120)
                event_type = event["type"]
                event_data = json.dumps(event["data"], ensure_ascii=False)

                yield f"event: {event_type}\ndata: {event_data}\n\n"

                # Stop streaming when we get the end event
                if event_type == "end":
                    break

            except queue.Empty:
                # Send keepalive
                yield f"event: keepalive\ndata: {{}}\n\n"
            except Exception:
                break

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )


@app.route("/api/stop", methods=["POST"])
def stop():
    """Stop the currently running agent."""
    global current_agent
    if current_agent:
        current_agent.stop()
        return jsonify({"success": True, "message": "Agent stopped"})
    return jsonify({"success": False, "message": "No agent running"})


@app.route("/api/session/reset", methods=["POST"])
def session_reset():
    """Clear memory for a given session."""
    data = request.json or {}
    session_id = data.get("session_id", "web_default").strip()
    reset_session_by_id(session_id)
    return jsonify({"success": True, "message": "Session memory cleared", "session_id": session_id})


@app.route("/api/session/info", methods=["GET"])
def session_info_endpoint():
    """Retrieve turn count and message statistics for a session."""
    session_id = request.args.get("session_id", "web_default").strip()
    info = get_session_info(session_id)
    return jsonify(info)


@app.route("/api/sessions", methods=["GET"])
def get_sessions_list():
    """Retrieve all saved sessions with metadata for UI drawer."""
    sessions = list_all_sessions()
    return jsonify({"success": True, "sessions": sessions})


@app.route("/api/session/<session_id>", methods=["GET"])
def get_session_detail(session_id):
    """Retrieve complete session history for UI restoration."""
    clean_id = session_id.strip()
    data = get_full_session_data(clean_id)
    return jsonify({"success": True, "session": data})


@app.route("/api/session/new", methods=["POST"])
def create_new_session_endpoint():
    """Create a new unique session and return its metadata."""
    data = request.json or {}
    title = data.get("title", "").strip() or None
    import session_manager
    new_sess = session_manager.create_new_session(title=title)
    return jsonify({"success": True, "session": new_sess})


@app.route("/api/session/<session_id>", methods=["DELETE"])
def delete_session_endpoint(session_id):
    """Delete a session from disk and memory."""
    clean_id = session_id.strip()
    success = delete_session_by_id(clean_id)
    return jsonify({"success": success, "session_id": clean_id})


@app.route("/api/settings", methods=["GET", "POST"])
def settings_endpoint():
    """Retrieve or update system settings (e.g. max_steps)."""
    if request.method == "POST":
        data = request.json or {}
        max_steps = data.get("max_steps")
        if max_steps is not None:
            try:
                max_steps = max(5, min(int(max_steps), 100))
                save_settings({"max_steps": max_steps})
                return jsonify({"success": True, "max_steps": max_steps, "message": "Settings saved successfully"})
            except (ValueError, TypeError):
                return jsonify({"success": False, "message": "Invalid max_steps value"}), 400
        return jsonify({"success": False, "message": "No valid settings provided"}), 400

    settings = load_settings()
    return jsonify(settings)


@app.route("/api/exec", methods=["POST"])
def exec_cmd():
    """Execute a single shell command manually on the SSH connection."""
    global ssh
    if not ssh.is_connected():
        return jsonify({"success": False, "stderr": "Not connected to any server", "exit_code": -1}), 400

    data = request.json or {}
    command = data.get("command", "").strip()
    sudo = bool(data.get("sudo", False))

    if not command:
        return jsonify({"success": False, "stderr": "Empty command", "exit_code": -1}), 400

    if sudo:
        result = ssh.execute_sudo_command(command)
    else:
        result = ssh.execute_command(command)

    return jsonify({
        "success": result["success"],
        "stdout": result["stdout"],
        "stderr": result["stderr"],
        "exit_code": result["exit_code"],
        "command": command,
        "username": ssh.username,
        "hostname": ssh.hostname,
        "cwd": result.get("cwd", ssh.cwd),
        "display_path": result.get("display_path", ssh.get_display_path())
    })


@app.route("/api/metrics", methods=["GET"])
def get_metrics():
    """Retrieve server performance metrics."""
    global ssh
    if not ssh.is_connected():
        return jsonify({"connected": False}), 200

    try:
        batch_cmd = (
            "cat /proc/loadavg; echo '---SEP---'; "
            "free -m; echo '---SEP---'; "
            "df -m / | tail -1; echo '---SEP---'; "
            "uptime -p; echo '---SEP---'; "
            "docker ps -q 2>/dev/null | wc -l"
        )
        res = ssh.execute_command(batch_cmd)
        if not res["success"] or not res["stdout"]:
            return jsonify({"connected": True, "error": res["stderr"]}), 200

        parts = res["stdout"].split("---SEP---")
        load_avg = parts[0].strip().split()[:3] if len(parts) > 0 else ["0", "0", "0"]

        ram_total, ram_used, ram_free = 0, 0, 0
        if len(parts) > 1:
            for line in parts[1].strip().splitlines():
                if line.startswith("Mem:"):
                    fields = line.split()
                    if len(fields) >= 3:
                        ram_total = int(fields[1])
                        ram_used = int(fields[2])
                        ram_free = ram_total - ram_used

        disk_total, disk_used, disk_free = 0, 0, 0
        if len(parts) > 2:
            df_fields = parts[2].strip().split()
            if len(df_fields) >= 4:
                disk_total = int(df_fields[1])
                disk_used = int(df_fields[2])
                disk_free = int(df_fields[3])

        uptime = parts[3].strip() if len(parts) > 3 else "N/A"
        docker_count = int(parts[4].strip()) if len(parts) > 4 and parts[4].strip().isdigit() else 0

        ram_percent = round((ram_used / ram_total * 100), 1) if ram_total > 0 else 0
        disk_percent = round((disk_used / disk_total * 100), 1) if disk_total > 0 else 0

        return jsonify({
            "connected": True,
            "hostname": ssh.hostname,
            "username": ssh.username,
            "uptime": uptime,
            "load_avg": load_avg,
            "ram": {
                "total_mb": ram_total,
                "used_mb": ram_used,
                "free_mb": ram_free,
                "percent": ram_percent
            },
            "disk": {
                "total_mb": disk_total,
                "used_mb": disk_used,
                "free_mb": disk_free,
                "percent": disk_percent
            },
            "docker_running": docker_count
        })
    except Exception as e:
        return jsonify({"connected": True, "error": str(e)}), 200


@app.route("/api/docker/list", methods=["GET"])
def docker_list():
    """List all Docker containers."""
    global ssh
    if not ssh.is_connected():
        return jsonify({"success": False, "message": "Not connected", "containers": []}), 200

    cmd = "docker ps -a --format '{{.ID}}|||{{.Names}}|||{{.Image}}|||{{.Status}}|||{{.State}}|||{{.Ports}}'"
    res = ssh.execute_command(cmd)
    if not res["success"]:
        return jsonify({"success": False, "error": res["stderr"], "containers": []})

    containers = []
    for line in res["stdout"].strip().splitlines():
        if not line.strip():
            continue
        parts = line.split("|||")
        if len(parts) >= 5:
            containers.append({
                "id": parts[0].strip(),
                "name": parts[1].strip(),
                "image": parts[2].strip(),
                "status": parts[3].strip(),
                "state": parts[4].strip().lower(),
                "ports": parts[5].strip() if len(parts) > 5 else ""
            })

    return jsonify({"success": True, "containers": containers})


@app.route("/api/docker/action", methods=["POST"])
def docker_action():
    """Perform action on a container (restart, stop, start, prune)."""
    global ssh
    if not ssh.is_connected():
        return jsonify({"success": False, "message": "Not connected"}), 400

    data = request.json or {}
    action = data.get("action", "").strip().lower()
    target = data.get("target", "").strip()

    if action == "prune":
        res = ssh.execute_command("docker system prune -f")
    elif action in ("restart", "stop", "start") and target:
        clean_target = "".join(c for c in target if c.isalnum() or c in ("-", "_", "."))
        res = ssh.execute_command(f"docker {action} {clean_target}")
    else:
        return jsonify({"success": False, "message": "Invalid action or target"}), 400

    return jsonify({
        "success": res["success"],
        "stdout": res["stdout"],
        "stderr": res["stderr"],
        "action": action,
        "target": target
    })


@app.route("/api/docker/logs", methods=["GET"])
def docker_logs():
    """Get logs for a container."""
    global ssh
    if not ssh.is_connected():
        return jsonify({"success": False, "message": "Not connected"}), 400

    container = request.args.get("container", "").strip()
    clean_target = "".join(c for c in container if c.isalnum() or c in ("-", "_", "."))
    if not clean_target:
        return jsonify({"success": False, "message": "Container name required"}), 400

    res = ssh.execute_command(f"docker logs --tail 100 {clean_target}")
    logs = res["stdout"] or res["stderr"] or "No logs available."
    return jsonify({"success": True, "container": clean_target, "logs": logs})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5050))
    print("=" * 60)
    print("  ⚡ AssisSSH — Autonomous AI DevOps & SSH Copilot")
    print(f"  Web UI:       http://localhost:{port}")
    print("  Telegram Bot: Active (Security: @Yahya_el_hamzawy)")
    print("=" * 60)
    
    # Start Telegram bot in background daemon thread
    start_bot_background(shared_ssh=ssh)
    
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
