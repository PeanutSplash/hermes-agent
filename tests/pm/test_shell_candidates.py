"""Bash resolution as pure data. Windows: Program Files Git beats PATH, and
the WSL / MSIX stubs never win (#116818). POSIX: the Nix profiles are searched
when PATH has no bash, and a login shell that is not bash never wins. The
candidate ladders take the ``which`` result and env as arguments."""
import pytest

from pm.shell import posix_bash_candidates, windows_bash_candidates

PF = r"D:\Progs"


@pytest.mark.parametrize(
    "stub",
    [r"C:\Windows\System32\bash.exe", r"C:\WINDOWS\system32\bash.exe",
     r"C:\Users\u\AppData\Local\Microsoft\WindowsApps\bash.exe"],
)
def test_system_stub_bash_is_never_a_candidate(stub):
    assert stub not in windows_bash_candidates(stub, {"ProgramFiles": PF})


def test_program_files_git_precedes_the_path_bash():
    on_path = r"C:\msys64\usr\bin\bash.exe"
    candidates = windows_bash_candidates(on_path, {"ProgramFiles": PF})
    assert candidates[0] == PF + r"\Git\bin\bash.exe"
    assert candidates[-1] == on_path

def test_per_user_and_32bit_git_roots_are_candidates():
    candidates = windows_bash_candidates(None, {
        "ProgramFiles": PF, "ProgramFiles(x86)": r"D:\Progs32",
        "LOCALAPPDATA": r"C:\Users\u\AppData\Local",
    })
    assert r"D:\Progs32\Git\bin\bash.exe" in candidates
    assert r"C:\Users\u\AppData\Local\Programs\Git\bin\bash.exe" in candidates
    assert r"C:\Users\u\AppData\Local\hermes\git\usr\bin\bash.exe" in candidates

NIX_ENV = {"HOME": "/home/u", "USER": "u"}


@pytest.mark.platforms("posix")
def test_nix_profile_bash_is_a_candidate_when_path_has_none():
    candidates = posix_bash_candidates(NIX_ENV)
    assert "/run/current-system/sw/bin/bash" in candidates
    assert "/etc/profiles/per-user/u/bin/bash" in candidates
    assert "/home/u/.nix-profile/bin/bash" in candidates


@pytest.mark.platforms("posix")
@pytest.mark.parametrize("login_shell", ["/run/current-system/sw/bin/zsh", "/bin/sh", "/usr/bin/fish"])
def test_a_login_shell_that_is_not_bash_is_never_a_candidate(login_shell):
    assert login_shell not in posix_bash_candidates({**NIX_ENV, "SHELL": login_shell})


@pytest.mark.platforms("posix")
def test_a_bash_login_shell_outside_the_known_dirs_is_a_candidate():
    assert "/opt/tools/bin/bash" in posix_bash_candidates({**NIX_ENV, "SHELL": "/opt/tools/bin/bash"})


def test_nonstarting_bash_is_rejected(monkeypatch):
    import subprocess
    from pm import shell

    monkeypatch.setattr(shell.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 1))
    assert shell._bash_starts("broken-bash.exe") is False
