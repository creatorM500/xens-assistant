import json, subprocess, sys, os, shlex
from .registry import register

_MAX_OUTPUT = 10000
_TIMEOUT = 60

@register(name="run_command", description="Run a shell command. Use this for system commands, git, npm, etc. Use execute_code for running code snippets.", tier="free")
def run_command(command: str, timeout: int = 30, workdir: str = "", shell: bool = True) -> str:
    if not command or not command.strip():
        return json.dumps({"error": "No command provided", "success": False})

    timeout = max(5, min(timeout, 120))
    cwd = workdir.strip() if workdir.strip() else None

    shell_exe = os.environ.get("COMSPEC", "cmd.exe") if sys.platform == "win32" else "/bin/bash"

    try:
        if sys.platform == "win32" and shell:
            proc = subprocess.run(
                [shell_exe, "/c" if "cmd" in shell_exe.lower() else "-Command", command],
                capture_output=True, text=True, timeout=timeout, cwd=cwd
            )
        elif shell:
            proc = subprocess.run(
                command, capture_output=True, text=True, timeout=timeout,
                shell=True, executable=shell_exe, cwd=cwd
            )
        else:
            parts = shlex.split(command)
            proc = subprocess.run(
                parts, capture_output=True, text=True, timeout=timeout, cwd=cwd
            )

        out = {
            "success": proc.returncode == 0,
            "returncode": proc.returncode,
            "command": command[:200],
        }
        if proc.stdout:
            out["output"] = proc.stdout[:_MAX_OUTPUT]
        if proc.stderr:
            out["error"] = proc.stderr[:_MAX_OUTPUT // 2]
        if proc.stdout and len(proc.stdout) > _MAX_OUTPUT:
            out["truncated"] = True
        return json.dumps(out)

    except FileNotFoundError:
        return json.dumps({"error": f"Shell not found: {shell_exe}", "success": False})
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Command timed out after {timeout}s", "success": False})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})
