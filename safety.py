"""Safety — destructive tool-call detection (single policy source).

One policy, one source: ``POLICY`` declares the name-based destructive set
plus the terminal command patterns; ``is_destructive()`` consumes it, and
the generated replay template embeds the same policy. A denylist is not a
sandbox — see the docstring caveat; unattended replay should use a
read-only allowlist (``READ_ONLY_TOOLS``).
"""

import re

#: Name-based policy: these tools always count as destructive.
DESTRUCTIVE_TOOL_NAMES = frozenset({"terminal", "patch", "write_file", "execute_code"})

# Patterns marking a terminal command destructive: rm, mkfs/dd, fork bomb,
# shutdown/reboot, recursive chmod/chown, output redirection, mv,
# find -delete, git reset --hard, package removal, chained commands.
_DESTRUCTIVE_PATTERNS = [
    re.compile(r"\brm\b"),  # rm / rm -rf / ...
    re.compile(r"\bmkfs\b"),
    re.compile(r"\bdd\b"),
    re.compile(r":\(\)\s*\{"),  # fork bomb
    re.compile(r"\bshutdown\b"),
    re.compile(r"\breboot\b"),
    re.compile(r"\bchmod\b.*-R"),
    re.compile(r"\bchown\b.*-R"),
    re.compile(r">"),  # output redirection (>, >>, 2>, &>)
    re.compile(r"\bmv\b"),
    re.compile(r"\bfind\b.*-delete"),
    re.compile(r"\bgit\b.*reset\s+--hard"),
    re.compile(r"\b(apt(-get)?|dnf|yum|pacman|brew|pip|npm)\b.*\b(remove|uninstall|purge)\b"),
    re.compile(r"(&&|\|\||;)\s*\S"),  # chained commands
]

#: Tools safe for unattended replay. Everything else needs approval.
READ_ONLY_TOOLS = frozenset({"read_file", "search_files", "vision_analyze", "web_search", "web_extract"})

#: The single policy object. Consumers must read from here, not copy it.
POLICY = {
    "destructive_names": set(DESTRUCTIVE_TOOL_NAMES),
    "destructive_patterns": [p.pattern for p in _DESTRUCTIVE_PATTERNS],
    "read_only_tools": set(READ_ONLY_TOOLS),
    "caveat": (
        "A denylist is not a sandbox: novel destructive commands always "
        "exist outside any pattern list. Unattended replay must use the "
        "read-only allowlist; --allow-destructive is an explicit operator "
        "opt-in, never a default."
    ),
}

# Backwards-compatible alias (was the whole policy before POLICY existed).
DESTRUCTIVE_TOOLS = set(DESTRUCTIVE_TOOL_NAMES)


def is_destructive(name: str, args: dict) -> bool:
    """Return True if calling tool `name` with `args` is destructive."""
    if name in DESTRUCTIVE_TOOL_NAMES:
        if name == "terminal":
            cmd = ""
            if isinstance(args, dict):
                cmd = str(args.get("command", ""))
            return any(p.search(cmd) for p in _DESTRUCTIVE_PATTERNS)
        return True
    if name != "terminal":
        return False
    cmd = str(args.get("command", "")) if isinstance(args, dict) else ""
    return any(p.search(cmd) for p in _DESTRUCTIVE_PATTERNS)
