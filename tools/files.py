import os, json, re, base64, hashlib, mimetypes, difflib
from pathlib import Path
from .registry import register

_MAX_TEXT_SIZE = 1 * 1024 * 1024
_MAX_TREE_DEPTH = 4

_TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
    ".toml", ".ini", ".cfg", ".conf", ".xml", ".html", ".htm", ".css", ".scss",
    ".less", ".sql", ".sh", ".bat", ".ps1", ".env", ".gitignore", ".dockerfile",
    ".yml", ".yaml", ".c", ".h", ".cpp", ".hpp", ".java", ".rs", ".go", ".rb",
    ".php", ".swift", ".kt", ".gradle", ".properties", ".csv", ".tsv",
    ".vue", ".svelte", ".astro", ".mjs", ".cjs", ".mts", ".cts",
}

_BINARY_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin",
    ".mp3", ".mp4", ".avi", ".mov", ".wav", ".flac", ".ogg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".pyc", ".pyo", ".pyd",
    ".db", ".sqlite", ".sqlite3",
}

_HOME = os.path.expanduser("~")
_TEMP = os.environ.get("TEMP", os.environ.get("TMP", ""))

def _resolve(path_str, base=None):
    if not path_str or not isinstance(path_str, str):
        raise ValueError("Path must be a non-empty string")
    p = Path(path_str)
    if not p.is_absolute():
        base = Path(base) if base else Path.cwd()
        p = base / p
    p = p.resolve()

    blocked = {"C:\\Windows", "C:\\Windows\\System32", "C:\\Program Files", "C:\\Program Files (x86)"}
    for b in blocked:
        if p.is_relative_to(Path(b)):
            raise PermissionError(f"Access denied to system directory: {b}")

    xens_state = Path(_HOME) / ".ainslup"
    if p.is_relative_to(xens_state):
        raise PermissionError("Access denied to Ainslup internal state (~/.ainslup)")

    return p

@register(name="read_file", description="Read a file. Supports text, binary, and partial reads with offset/limit.", tier="free")
def read_file(path: str, binary: bool = False, offset: int = 0, limit: int = 2000) -> str:
    try:
        p = _resolve(path)
        if not p.exists():
            return json.dumps({"error": f"File not found: {p}", "success": False})
        if not p.is_file():
            return json.dumps({"error": f"Not a file: {p}", "success": False})

        size = p.stat().st_size
        if binary or p.suffix.lower() in _BINARY_EXTENSIONS:
            if size > 10 * 1024 * 1024:
                return json.dumps({"error": "File too large for binary read", "success": False})
            data = p.read_bytes()
            b64 = base64.b64encode(data).decode()
            mime = mimetypes.guess_type(str(p))[0] or "application/octet-stream"
            return json.dumps({
                "success": True,
                "filename": p.name,
                "path": str(p),
                "size": size,
                "mime_type": mime,
                "base64": b64,
                "binary": True,
            })

        if p.suffix.lower() not in _TEXT_EXTENSIONS and size > 100000:
            return json.dumps({"error": "Unknown file type - use binary=true to read as binary", "success": False})

        if size > _MAX_TEXT_SIZE:
            return json.dumps({"error": f"File too large ({size} bytes, max {_MAX_TEXT_SIZE})", "success": False})

        try:
            text = p.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            return json.dumps({"error": "File is not valid UTF-8 - use binary=true to read as binary", "success": False})

        lines = text.splitlines(keepends=True)
        total_lines = len(lines)

        if offset > 0 or limit:
            start = max(0, offset - 1)
            end = min(total_lines, start + limit) if limit else total_lines
            text = "".join(lines[start:end])
            metadata = {
                "success": True, "filename": p.name, "path": str(p),
                "size": size, "lines": total_lines,
                "offset": start + 1, "limit": limit,
                "truncated": end < total_lines,
            }
        else:
            metadata = {
                "success": True, "filename": p.name, "path": str(p),
                "size": size, "lines": total_lines,
            }

        metadata["content"] = text
        return json.dumps(metadata)

    except PermissionError as e:
        return json.dumps({"error": str(e), "success": False})
    except ValueError as e:
        return json.dumps({"error": str(e), "success": False})
    except Exception as e:
        return json.dumps({"error": f"Failed to read file: {e}", "success": False})

@register(name="write_file", description="Write content to a file. Creates directories. Supports append mode and binary base64 write.", tier="free")
def write_file(path: str, content: str = "", binary: bool = False, append: bool = False) -> str:
    try:
        p = _resolve(path)
        if p.is_dir():
            return json.dumps({"error": f"Path is a directory: {p}", "success": False})

        p.parent.mkdir(parents=True, exist_ok=True)

        mode = "ab" if (binary or append) else "w"
        if binary:
            data = base64.b64decode(content) if content else b""
            p.write_bytes(data)
        elif append:
            with p.open("a", encoding="utf-8") as f:
                f.write(content)
        else:
            p.write_text(content, encoding="utf-8")

        size = p.stat().st_size
        action = "Appended" if append else "Wrote"
        return json.dumps({
            "success": True, "action": action,
            "path": str(p), "size": size
        })

    except PermissionError as e:
        return json.dumps({"error": str(e), "success": False})
    except ValueError as e:
        return json.dumps({"error": str(e), "success": False})
    except Exception as e:
        return json.dumps({"error": f"Failed to write file: {e}", "success": False})

@register(name="list_dir", description="List files and directories with size, type, and modification time. Supports recursive depth and name filtering.", tier="free")
def list_dir(path: str = ".", depth: int = 1, pattern: str = None) -> str:
    try:
        p = _resolve(path)
        if not p.exists():
            return json.dumps({"error": f"Directory not found: {p}", "success": False})
        if not p.is_dir():
            return json.dumps({"error": f"Not a directory: {p}", "success": False})

        depth = max(1, min(depth, _MAX_TREE_DEPTH))
        entries = []

        def _walk(dir_path, current_depth):
            if current_depth > depth:
                return
            try:
                children = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            except PermissionError:
                entries.append({"name": dir_path.name + "/", "type": "dir", "error": "Permission denied"})
                return

            for child in children:
                if child.name.startswith("."):
                    continue
                if pattern and pattern not in child.name:
                    continue

                try:
                    stat = child.stat()
                    entry = {
                        "name": child.name + "/" if child.is_dir() else child.name,
                        "type": "dir" if child.is_dir() else "file",
                        "size": stat.st_size if not child.is_dir() else 0,
                        "modified": stat.st_mtime,
                    }
                except OSError:
                    entry = {
                        "name": child.name + "/" if child.is_dir() else child.name,
                        "type": "dir" if child.is_dir() else "file",
                    }

                entries.append(entry)
                if child.is_dir() and current_depth < depth:
                    _walk(child, current_depth + 1)

        _walk(p, 1)
        return json.dumps({
            "success": True,
            "path": str(p),
            "entries": entries,
            "count": len(entries),
        })

    except PermissionError as e:
        return json.dumps({"error": str(e), "success": False})
    except ValueError as e:
        return json.dumps({"error": str(e), "success": False})
    except Exception as e:
        return json.dumps({"error": f"Failed to list directory: {e}", "success": False})

@register(name="grep_files", description="Search file contents by pattern. Supports regex or plain text matching.", tier="free")
def grep_files(root: str = ".", pattern: str = "", include: str = None, max_results: int = 50) -> str:
    if not pattern:
        return json.dumps({"error": "Search pattern is required", "success": False})

    try:
        root_path = _resolve(root)
        if not root_path.exists():
            return json.dumps({"error": f"Directory not found: {root_path}", "success": False})

        max_results = max(1, min(max_results, 200))
        results = []
        matched_files = set()
        skipped_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".tox", ".eggs", "build", "dist", ".next", ".nuxt", ".git-svn"}

        try:
            import re as regex
            compiled = regex.compile(pattern)
        except:
            compiled = None

        for dirpath, dirnames, filenames in os.walk(str(root_path)):
            dirnames[:] = [d for d in dirnames if d not in skipped_dirs]

            for filename in filenames:
                if include:
                    if not filename.endswith(tuple(include.split(","))):
                        continue

                if len(results) >= max_results:
                    break

                fpath = os.path.join(dirpath, filename)
                try:
                    if os.path.getsize(fpath) > 1024 * 1024:
                        continue
                    with open(fpath, "r", encoding="utf-8-sig", errors="replace") as f:
                        for line_no, line in enumerate(f, 1):
                            line = line.rstrip("\n\r")
                            if compiled:
                                m = compiled.search(line)
                                if m:
                                    col = m.start() + 1
                                    results.append({
                                        "file": fpath,
                                        "line": line_no,
                                        "column": col,
                                        "content": line[:300],
                                    })
                            elif pattern in line:
                                results.append({
                                    "file": fpath,
                                    "line": line_no,
                                    "content": line[:300],
                                })
                            if len(results) >= max_results:
                                break
                except:
                    continue

            if len(results) >= max_results:
                break

        resp = {
            "success": True,
            "pattern": pattern,
            "results": results,
            "count": len(results),
            "truncated": len(results) == max_results,
        }
        return json.dumps(resp)

    except PermissionError as e:
        return json.dumps({"error": str(e), "success": False})
    except ValueError as e:
        return json.dumps({"error": str(e), "success": False})
    except Exception as e:
        return json.dumps({"error": f"Failed to search: {e}", "success": False})

@register(name="diff_files", description="Compare two files line-by-line. Returns a unified diff.", tier="free")
def diff_files(path_a: str, path_b: str, context_lines: int = 3) -> str:
    try:
        pa = _resolve(path_a)
        pb = _resolve(path_b)
    except (PermissionError, ValueError) as e:
        return json.dumps({"error": str(e), "success": False})
    try:
        with open(pa, "r", encoding="utf-8-sig", errors="replace") as f:
            content_a = f.read()
    except FileNotFoundError:
        return json.dumps({"error": f"File not found: {pa}", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Failed to read {pa}: {e}", "success": False})
    try:
        with open(pb, "r", encoding="utf-8-sig", errors="replace") as f:
            content_b = f.read()
    except FileNotFoundError:
        return json.dumps({"error": f"File not found: {pb}", "success": False})
    except Exception as e:
        return json.dumps({"error": f"Failed to read {pb}: {e}", "success": False})
    if content_a == content_b:
        return json.dumps({"success": True, "identical": True, "diff": "Files are identical"})
    lines_a = content_a.splitlines(keepends=True)
    lines_b = content_b.splitlines(keepends=True)
    context_lines = max(0, min(context_lines, 20))
    diff = list(difflib.unified_diff(lines_a, lines_b, fromfile=str(pa), tofile=str(pb), n=context_lines))
    diff_text = "".join(diff)
    return json.dumps({"success": True, "identical": False, "lines_a": len(lines_a), "lines_b": len(lines_b), "diff_lines": len(diff), "diff": diff_text[:10000], "truncated": len(diff_text) > 10000})
