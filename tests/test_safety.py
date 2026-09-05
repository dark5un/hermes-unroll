"""Tests for safety.is_destructive — destructive tool-call detection (G3)."""
from safety import DESTRUCTIVE_TOOLS, is_destructive


def test_destructive_tools_set():
    assert DESTRUCTIVE_TOOLS == {"terminal", "patch", "write_file", "execute_code"}


def test_terminal_rm_rf_is_destructive():
    assert is_destructive("terminal", {"command": "rm -rf /"}) is True


def test_terminal_rm_is_destructive():
    assert is_destructive("terminal", {"command": "rm file.txt"}) is True


def test_terminal_mkfs_dd_destructive():
    assert is_destructive("terminal", {"command": "mkfs.ext4 /dev/sda1"}) is True
    assert is_destructive("terminal", {"command": "dd if=/dev/zero of=/dev/sda"}) is True


def test_terminal_forkbomb_shutdown_reboot_destructive():
    assert is_destructive("terminal", {"command": ":(){ :|:& };:"}) is True
    assert is_destructive("terminal", {"command": "shutdown now"}) is True
    assert is_destructive("terminal", {"command": "sudo reboot"}) is True


def test_terminal_chmod_chown_recursive_destructive():
    assert is_destructive("terminal", {"command": "chmod -R 777 /etc"}) is True
    assert is_destructive("terminal", {"command": "chown -R user /"}) is True


def test_terminal_safe_commands_not_destructive():
    assert is_destructive("terminal", {"command": "ls -la"}) is False
    assert is_destructive("terminal", {"command": "echo hello"}) is False
    assert is_destructive("terminal", {"command": "cat file.txt"}) is False


def test_patch_write_execute_always_destructive():
    assert is_destructive("patch", {}) is True
    assert is_destructive("write_file", {"path": "a.txt"}) is True
    assert is_destructive("execute_code", {"code": "print(1)"}) is True


def test_read_file_never_destructive():
    assert is_destructive("read_file", {"path": "a.txt"}) is False
    assert is_destructive("unknown_tool", {}) is False
