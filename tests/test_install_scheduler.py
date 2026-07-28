"""Exercises scripts/install_scheduler.sh as a subprocess.

Real `launchctl` and `osascript` must never run from a test, so every test
here puts a no-op stub named "launchctl" first on PATH and points HOME at
tmp_path -- the script only ever touches ~/Library/LaunchAgents and (via the
stub) "launchctl", so nothing outside tmp_path is written and no real agent
is ever loaded, booted, or unloaded.
"""
import os
import stat
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL_SCRIPT = os.path.join(REPO_ROOT, "scripts", "install_scheduler.sh")
LABEL = "com.mishka.mail-automator"


def _make_executable(path, content):
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _fake_project(tmp_path, name="AT&T Corp"):
    """A copy of the real script + template under a path containing '&'.

    The '&' is the point: it is sed's whole-match token, so a project path
    containing one is exactly the case Finding 6 covers.
    """
    project = tmp_path / name
    (project / "scripts").mkdir(parents=True)
    (project / "logs").mkdir()
    (project / ".venv" / "bin").mkdir(parents=True)

    script_text = open(INSTALL_SCRIPT).read()
    (project / "scripts" / "install_scheduler.sh").write_text(script_text)
    os.chmod(project / "scripts" / "install_scheduler.sh", 0o755)

    template_src = os.path.join(REPO_ROOT, "scripts", f"{LABEL}.plist.template")
    (project / "scripts" / f"{LABEL}.plist.template").write_text(open(template_src).read())

    # Stub python: install_scheduler.sh only checks it is executable.
    _make_executable(project / ".venv" / "bin" / "python", "#!/bin/sh\nexit 0\n")
    return project


def _stub_bin(tmp_path, log_name="launchctl.log"):
    """A bin/ dir with a no-op 'launchctl' that records its invocations."""
    bindir = tmp_path / "stubbin"
    bindir.mkdir()
    log = tmp_path / log_name
    _make_executable(
        bindir / "launchctl",
        f'#!/bin/sh\necho "$@" >> "{log}"\nexit 0\n',
    )
    return bindir, log


def _run(script, args, home, bindir):
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["PATH"] = f"{bindir}:{env.get('PATH', '')}"
    return subprocess.run(
        ["bash", str(script), *args],
        env=env, capture_output=True, text=True, timeout=30,
    )


# --- Finding 7: a typo'd flag must not silently install -----------------------

@pytest.mark.parametrize("bad_args", [["--uninstal"], ["-u"], ["--off"], ["a", "b"]])
def test_bad_flag_refuses_to_install(tmp_path, bad_args):
    home = tmp_path / "home"
    home.mkdir()
    bindir, log = _stub_bin(tmp_path)

    result = _run(INSTALL_SCRIPT, bad_args, home, bindir)

    assert result.returncode == 1
    assert "usage" in (result.stdout + result.stderr).lower()
    # Must never have reached the point of touching launchctl at all.
    assert not log.exists()
    assert not (home / "Library" / "LaunchAgents" / f"{LABEL}.plist").exists()


def test_no_args_is_the_only_install_trigger(tmp_path):
    """Sanity check the parser accepts the documented no-argument form
    (the real install is exercised separately in test_ampersand_project_path...)."""
    project = _fake_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    bindir, log = _stub_bin(tmp_path)

    result = _run(project / "scripts" / "install_scheduler.sh", [], home, bindir)

    assert result.returncode == 0, result.stdout + result.stderr
    assert log.read_text()  # launchctl (the stub) was invoked to install


# --- Finding 6: '&' in the project path must not corrupt the plist -----------

def test_ampersand_in_project_path_is_escaped_in_installed_plist(tmp_path):
    project = _fake_project(tmp_path, name="AT&T Corp")
    home = tmp_path / "home"
    home.mkdir()
    bindir, log = _stub_bin(tmp_path)

    result = _run(project / "scripts" / "install_scheduler.sh", [], home, bindir)
    assert result.returncode == 0, result.stdout + result.stderr

    plist = (home / "Library" / "LaunchAgents" / f"{LABEL}.plist").read_text()
    assert "__PROJECT__" not in plist, "placeholder must be fully substituted"
    assert "__PYTHON__" not in plist, "placeholder must be fully substituted"
    assert str(project) in plist, "the '&' must survive as a literal character"
    assert str(project / ".venv" / "bin" / "python") in plist


def test_uninstall_removes_the_plist(tmp_path):
    project = _fake_project(tmp_path)
    home = tmp_path / "home"
    home.mkdir()
    bindir, log = _stub_bin(tmp_path)
    script = project / "scripts" / "install_scheduler.sh"

    assert _run(script, [], home, bindir).returncode == 0
    plist_path = home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    assert plist_path.exists()

    result = _run(script, ["--uninstall"], home, bindir)
    assert result.returncode == 0
    assert not plist_path.exists()
    assert "bootout" in log.read_text()
