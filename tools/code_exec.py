import sys, subprocess, os, json, tempfile, signal, textwrap, re
from .registry import register

_SAFE_GLOBALS = {
    "True": True, "False": False, "None": None,
    "abs": abs, "all": all, "any": any, "bin": bin, "bool": bool,
    "chr": chr, "dict": dict, "dir": dir, "divmod": divmod,
    "enumerate": enumerate, "filter": filter, "float": float,
    "format": format, "frozenset": frozenset, "getattr": getattr,
    "hasattr": hasattr, "hash": hash, "hex": hex, "id": id,
    "int": int, "isinstance": isinstance, "issubclass": issubclass,
    "iter": iter, "len": len, "list": list, "map": map,
    "max": max, "min": min, "next": next, "object": object,
    "oct": oct, "ord": ord, "pow": pow, "print": print,
    "range": range, "repr": repr, "reversed": reversed,
    "round": round, "set": set, "slice": slice, "sorted": sorted,
    "str": str, "sum": sum, "tuple": tuple, "type": type,
    "zip": zip, "__import__": __import__,
}

_DANGEROUS = [
    "os", "subprocess", "shutil", "socket", "ctypes",
    "inspect", "importlib", "compile", "exec", "eval",
    "open", "__import__", "getattr", "setattr", "delattr",
]

_TIMEOUT = 30
_MAX_OUTPUT = 10000
_MAX_CODE = 50000

def _sanitize(code):
    if len(code) > _MAX_CODE:
        return None, "Code exceeds maximum length"
    for word in _DANGEROUS:
        pattern = r'(^|[^a-zA-Z0-9_])' + re.escape(word) + r'($|[^a-zA-Z0-9_])'
        if re.search(pattern, code):
            return None, f"Use of '{word}' is not allowed in sandboxed execution"
    return code, None

@register(name="execute_code", description="Execute Python, JavaScript, Bash, or PowerShell code. Returns output, errors, and return code.", tier="free")
def execute_code(code: str, language: str = "python") -> str:
    if not code or not code.strip():
        return json.dumps({"error": "No code provided", "success": False})

    handlers = {
        "python": _exec_python,
        "javascript": _exec_javascript,
        "js": _exec_javascript,
        "bash": _exec_bash,
        "sh": _exec_bash,
        "shell": _exec_bash,
        "cmd": _exec_bash,
        "powershell": _exec_powershell,
        "pwsh": _exec_powershell,
    }

    handler = handlers.get(language)
    if not handler:
        return json.dumps({"error": f"Unsupported language: '{language}'. Supported: {', '.join(sorted(set(handlers.keys()) - {'js', 'sh', 'shell', 'cmd', 'pwsh'}))}", "success": False})

    return handler(code)

def _exec_python(code):
    sanitized, error = _sanitize(code)
    if error:
        return json.dumps({"error": error, "success": False})

    if "\n" not in code.strip() and not code.strip().startswith(("print", "return", "import", "from", "def ", "class ", "if ", "for ", "while ", "try:", "with ", "raise")):
        wrapped = f"print(repr({code.strip()}))"
        try:
            compile(wrapped, "<test>", "exec")
            code = wrapped
        except:
            pass

    try:
        proc = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True,
            timeout=_TIMEOUT,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}
        )
        return _format_result(proc)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Execution timed out after {_TIMEOUT}s", "success": False})
    except FileNotFoundError:
        return json.dumps({"error": "Python interpreter not found", "success": False})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})

def _exec_javascript(code):
    try:
        proc = subprocess.run(
            ["node", "-e", code],
            capture_output=True, text=True, timeout=_TIMEOUT
        )
        return _format_result(proc)
    except FileNotFoundError:
        return json.dumps({
            "error": "Node.js not found. Install it from https://nodejs.org or use python/bash instead.",
            "success": False
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Execution timed out after {_TIMEOUT}s", "success": False})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})

def _exec_bash(code):
    try:
        proc = subprocess.run(
            code,
            capture_output=True, text=True, timeout=_TIMEOUT,
            shell=True, executable="cmd.exe" if sys.platform == "win32" else "/bin/bash"
        )
        return _format_result(proc)
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Execution timed out after {_TIMEOUT}s", "success": False})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})

def _exec_powershell(code):
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", code],
            capture_output=True, text=True, timeout=_TIMEOUT
        )
        return _format_result(proc)
    except FileNotFoundError:
        return json.dumps({
            "error": "PowerShell not found",
            "success": False
        })
    except subprocess.TimeoutExpired:
        return json.dumps({"error": f"Execution timed out after {_TIMEOUT}s", "success": False})
    except Exception as e:
        return json.dumps({"error": str(e), "success": False})

def _format_result(proc):
    out = {"success": proc.returncode == 0, "returncode": proc.returncode}
    if proc.stdout:
        out["output"] = proc.stdout[:_MAX_OUTPUT]
    if proc.stderr:
        out["error"] = proc.stderr[:_MAX_OUTPUT // 2]
    return json.dumps(out)
