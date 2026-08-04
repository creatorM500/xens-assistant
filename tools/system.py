import json, os, platform, sys, shutil, subprocess
from pathlib import Path
from .registry import register

@register(name="system_info", description="Get system info: environment, disk, memory, CPU, and optional project directory tree.", tier="free")
def system_info(project_root: str = None, tree_depth: int = 3, show_hidden: bool = False) -> str:
    info = {
        "os": platform.system(),
        "os_version": platform.version(),
        "os_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": sys.version.split()[0],
        "python_path": sys.executable,
        "hostname": platform.node(),
        "cwd": os.getcwd(),
        "home": os.path.expanduser("~"),
        "temp": os.environ.get("TEMP", ""),
        "path_count": len(os.environ.get("PATH", "").split(os.pathsep)),
        "shell": os.environ.get("SHELL", os.environ.get("COMSPEC", "")),
        "cpu_count": os.cpu_count() or 0,
    }
    try:
        total, used, free = shutil.disk_usage(os.getcwd())
        info["disk_total"] = f"{total / (1024**3):.1f}GB"
        info["disk_free"] = f"{free / (1024**3):.1f}GB"
    except:
        pass
    try:
        import psutil
        info["memory_total"] = f"{psutil.virtual_memory().total / (1024**3):.1f}GB"
        info["memory_available"] = f"{psutil.virtual_memory().available / (1024**3):.1f}GB"
        info["memory_percent"] = psutil.virtual_memory().percent
    except ImportError:
        pass
    if project_root:
        root_p = Path(project_root)
        if root_p.exists() and root_p.is_dir():
            depth = max(1, min(tree_depth, 5))
            skip = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".eggs", "build", "dist", ".next", ".nuxt", ".git-svn", ".ruff_cache", ".pytest_cache", ".mypy_cache", ".hypothesis", ".terraform"}
            tree_lines = [f"{root_p.name}/"]
            def _walk(dir_path, prefix, current_depth):
                if current_depth > depth:
                    return
                try:
                    entries = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
                except PermissionError:
                    return
                for i, child in enumerate(entries):
                    if child.name.startswith(".") and not show_hidden:
                        continue
                    if child.is_dir() and child.name in skip:
                        continue
                    is_last = i == len(entries) - 1
                    connector = "+-- " if is_last else "|-- "
                    try:
                        stat = child.stat()
                        count = sum(1 for _ in child.iterdir()) if child.is_dir() else 0
                        size = f" ({count} items)" if child.is_dir() and count > 0 else f" ({stat.st_size:,}B)"
                    except:
                        size = ""
                    tree_lines.append(f"{prefix}{connector}{child.name}{'/' if child.is_dir() else ''}{size}")
                    if child.is_dir() and current_depth < depth:
                        _walk(child, prefix + ("    " if is_last else "|   "), current_depth + 1)
            _walk(root_p, "", 1)
            info["project_tree"] = "\n".join(tree_lines)
    return json.dumps({"success": True, "info": info})
