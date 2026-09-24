"""
SSH Manager — إدارة اتصال SSH بالسيرفر
"""
import paramiko
import time


class SSHManager:
    """Manages SSH connections and command execution on a remote server."""

    def __init__(self):
        self.client = None
        self.hostname = None
        self.port = 22
        self.username = None
        self.password = None
        self.sudo_password = None
        self.connected = False
        self.cwd = None
        self.home_dir = None

    def get_display_path(self) -> str:
        """Return formatted path for bash prompt (e.g. ~, ~/Desktop, /var/log)."""
        if not self.cwd:
            return "~"
        home = self.home_dir or (f"/home/{self.username}" if self.username != "root" else "/root")
        if self.cwd == home:
            return "~"
        if home and self.cwd.startswith(home + "/"):
            return "~" + self.cwd[len(home):]
        if self.username == "root" and self.cwd == "/root":
            return "~"
        return self.cwd

    def connect(self, hostname: str, username: str, password: str,
                port: int = 22, sudo_password: str = None) -> dict:
        """
        Establish SSH connection to the remote server.

        Args:
            hostname: Server IP or domain
            username: SSH username
            password: SSH password
            port: SSH port (default 22)
            sudo_password: Optional sudo password

        Returns:
            dict with 'success' and 'message' keys
        """
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            self.hostname = hostname
            self.port = port
            self.username = username
            self.password = password
            self.sudo_password = sudo_password

            self.client.connect(
                hostname=self.hostname,
                port=self.port,
                username=self.username,
                password=self.password,
                timeout=15,
                look_for_keys=False,
                allow_agent=False
            )

            self.connected = True

            # Detect initial home and working directory
            try:
                stdin, stdout, stderr = self.client.exec_command("pwd", timeout=5)
                initial_pwd = stdout.read().decode("utf-8", errors="replace").strip()
                if initial_pwd:
                    self.home_dir = initial_pwd
                    self.cwd = initial_pwd
            except Exception:
                self.home_dir = f"/home/{self.username}" if self.username != "root" else "/root"
                self.cwd = self.home_dir

            return {
                "success": True, 
                "message": f"Connected to {hostname}:{port} as {username}",
                "cwd": self.cwd,
                "display_path": self.get_display_path()
            }

        except paramiko.AuthenticationException:
            self.connected = False
            return {"success": False, "message": "Authentication failed — check username/password"}
        except paramiko.SSHException as e:
            self.connected = False
            return {"success": False, "message": f"SSH error: {str(e)}"}
        except Exception as e:
            self.connected = False
            return {"success": False, "message": f"Connection failed: {str(e)}"}

    def execute_command(self, command: str, timeout: int = 60) -> dict:
        """
        Execute a command on the remote server.

        Args:
            command: Shell command to execute
            timeout: Command timeout in seconds

        Returns:
            dict with 'stdout', 'stderr', 'exit_code', 'success' keys
        """
        if not self.connected or not self.client:
            return {
                "stdout": "",
                "stderr": "Not connected to any server",
                "exit_code": -1,
                "success": False,
                "cwd": self.cwd,
                "display_path": self.get_display_path()
            }

        try:
            # Check if connection is still alive
            self.client.get_transport().send_ignore()
        except Exception:
            # Try to reconnect
            try:
                self.client.connect(
                    hostname=self.hostname,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=15,
                    look_for_keys=False,
                    allow_agent=False
                )
            except Exception as e:
                self.connected = False
                return {
                    "stdout": "",
                    "stderr": f"Connection lost and reconnection failed: {str(e)}",
                    "exit_code": -1,
                    "success": False,
                    "cwd": self.cwd,
                    "display_path": self.get_display_path()
                }

        DELIM = "___AGY_CWD_DELIM___"
        escaped_cwd = self.cwd.replace("'", "'\\''") if self.cwd else ""
        cwd_prefix = f"if [ -d '{escaped_cwd}' ]; then cd '{escaped_cwd}' 2>/dev/null; fi\n" if escaped_cwd else ""
        wrapped_command = (
            f"{cwd_prefix}"
            f"{command}\n"
            f"__AGY_EXIT__=$?\n"
            f"printf '%s' '{DELIM}'\n"
            f"pwd\n"
            f"exit $__AGY_EXIT__"
        )

        try:
            stdin, stdout, stderr = self.client.exec_command(wrapped_command, timeout=timeout)

            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            exit_code = stdout.channel.recv_exit_status()

            # Extract CWD from delimiter if present
            if DELIM in out:
                out_body, new_cwd = out.rsplit(DELIM, 1)
                new_cwd = new_cwd.strip()
                if new_cwd:
                    self.cwd = new_cwd
                out = out_body

            # Trim very long outputs to avoid overwhelming the AI
            max_len = 8000
            if len(out) > max_len:
                out = out[:max_len] + f"\n\n... [output trimmed, total {len(out)} chars]"
            if len(err) > max_len:
                err = err[:max_len] + f"\n\n... [error output trimmed, total {len(err)} chars]"

            return {
                "stdout": out,
                "stderr": err,
                "exit_code": exit_code,
                "success": exit_code == 0,
                "cwd": self.cwd,
                "display_path": self.get_display_path()
            }

        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"Command execution failed: {str(e)}",
                "exit_code": -1,
                "success": False,
                "cwd": self.cwd,
                "display_path": self.get_display_path()
            }

    def execute_sudo_command(self, command: str, timeout: int = 60) -> dict:
        """
        Execute a command with sudo privileges.

        Args:
            command: Shell command to execute with sudo
            timeout: Command timeout in seconds

        Returns:
            dict with 'stdout', 'stderr', 'exit_code', 'success' keys
        """
        sudo_pass = self.sudo_password or self.password

        if not sudo_pass:
            return {
                "stdout": "",
                "stderr": "No sudo password provided",
                "exit_code": -1,
                "success": False,
                "cwd": self.cwd,
                "display_path": self.get_display_path()
            }

        # Use -S to read password from stdin, -p '' to suppress prompt
        sudo_cmd = f"echo '{sudo_pass}' | sudo -S -p '' {command}"
        result = self.execute_command(sudo_cmd, timeout=timeout)

        # Clean up the sudo password prompt from stderr if present
        if result["stderr"]:
            lines = result["stderr"].split("\n")
            cleaned = [l for l in lines if not l.strip().startswith("[sudo]")]
            result["stderr"] = "\n".join(cleaned).strip()

        return result

    def disconnect(self):
        """Close the SSH connection."""
        if self.client:
            try:
                self.client.close()
            except Exception:
                pass
        self.connected = False
        self.client = None

    def is_connected(self) -> bool:
        """Check if SSH connection is active."""
        if not self.connected or not self.client:
            return False
        try:
            transport = self.client.get_transport()
            if transport and transport.is_active():
                transport.send_ignore()
                return True
        except Exception:
            pass
        self.connected = False
        return False
