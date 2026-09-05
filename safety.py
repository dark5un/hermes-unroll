"""Safety — destructive tool-call detection (G3)."""
import re

DESTRUCTIVE_TOOLS = {"terminal", "patch", "write_file", "execute_code"}

# Patterns marking a terminal command destructive.
_DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\b"),  # rm / rm -rf / ...
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\b"),
    re.compile(r":\(\)\s*\{"),
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bchmod\b.*-R"),
    re.compile(r"\bchown\b.*-R"),
]


def is_destructive(name: str, args: dict) -> bool:
    """Return True if calling tool `name` with `args` is destructive."""
    if name in ("patch", "write_file", "execute_code"):
        return True
    if name == "terminal":
        cmd = ""
        if isinstance(args, dict):
            cmd = str(args.get("command", ""))
        return any(p.search(cmd) for p in _DESTRUCTIVE_PATTERNS)
    return False
