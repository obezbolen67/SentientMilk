"""scripts/bundle.py: an app folder that runs on Python's own signed runtime, with no new program in it."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="the bundle is the Windows build")


def bundle(tmp_path):
    app = tmp_path / "src" / "tinyapp"
    app.mkdir(parents=True, exist_ok=True)
    (app / "__init__.py").write_text("import requests\nWHERE = __file__\n", encoding="utf-8")
    (app / "__main__.py").write_text("import sys\nprint('tiny ran', *sys.argv[1:])\n", encoding="utf-8")
    project = tmp_path / "src" / "pyproject.toml"  # a requirement for another platform is not looked up
    project.write_text('[project]\nname = "tiny"\nversion = "2.3.1"\nauthors = [{name = "Tiny Team"}]\n'
                       'dependencies = ["requests", "not-installed-anywhere; sys_platform == \'linux\'"]\n',
                       encoding="utf-8")
    out = tmp_path / "dist" / "Tiny"
    return subprocess.run([sys.executable, str(ROOT / "scripts" / "bundle.py"), "--name", "Tiny",
                           "--module", "tinyapp", "--package", str(app), "--project", str(project),
                           "--out", str(out), "--console"], capture_output=True, text=True), out


def test_the_app_runs_on_the_bundled_python_and_its_own_packages_only(tmp_path):
    done, out = bundle(tmp_path)
    assert done.returncode == 0, done.stderr
    shadow = tmp_path / "shadow" / "tinyapp"  # PYTHONPATH and the user's site-packages must not leak in
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("raise SystemExit('the wrong tinyapp')\n", encoding="utf-8")
    python = out / "runtime" / "python.exe"
    ran = subprocess.run([str(python), "-c", "import sys, tinyapp, requests, urllib3; print(tinyapp.WHERE); "
                          "print(sys.flags.no_user_site or not any('Roaming' in p for p in sys.path))"],
                         capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(shadow.parent)})
    assert ran.returncode == 0, ran.stderr
    where, isolated = ran.stdout.split()
    assert Path(where).is_relative_to(out) and isolated == "True"
    site = out / "runtime" / "Lib" / "site-packages"
    assert (site / "requests").is_dir() and not (site / "pytest").exists()  # only what the app needs
    programs = {p.relative_to(out).as_posix() for p in out.rglob("*.exe")}  # its own, and Python's signed ones
    assert {"Tiny.exe", "runtime/python.exe", "runtime/pythonw.exe"} <= programs
    assert all(p == "Tiny.exe" or p.count("/") == 1 or p.startswith("runtime/Lib/venv/scripts/") for p in programs)
    assert (out / "runtime" / "bundle.json").exists()
    assert subprocess.run([str(out / "Tiny.cmd")], capture_output=True, text=True).stdout.strip() == "tiny ran"
    assert (out / "Tiny.lnk").exists()


def test_files_git_ignores_stay_out_of_the_bundle(tmp_path):
    """A checkout keeps local settings, keys and databases beside the code; a shared build must not carry them."""
    source = tmp_path / "src"
    (source / "tinyapp" / "data").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(source)], check=True)
    (source / ".gitignore").write_text("tinyapp/config.json\ntinyapp/data/*\n", encoding="utf-8")
    (source / "tinyapp" / "config.json").write_text('{"api_key": "sk-secret"}', encoding="utf-8")
    (source / "tinyapp" / "data" / "history.db").write_text("chats", encoding="utf-8")
    (source / "tinyapp" / "new_module.py").write_text("X = 1\n", encoding="utf-8")  # not committed yet: still code
    done, out = bundle(tmp_path)
    assert done.returncode == 0, done.stderr
    app = out / "app" / "tinyapp"
    assert (app / "new_module.py").exists() and (app / "__main__.py").exists()
    assert not (app / "config.json").exists() and not (app / "data" / "history.db").exists()


def test_a_rebuild_replaces_a_bundle_but_never_another_folder(tmp_path):
    assert bundle(tmp_path)[0].returncode == 0
    again, out = bundle(tmp_path)
    assert again.returncode == 0, again.stderr
    other = tmp_path / "other"
    other.mkdir()
    (other / "keep.txt").write_text("mine", encoding="utf-8")
    refused = subprocess.run([sys.executable, str(ROOT / "scripts" / "bundle.py"), "--name", "Tiny", "--module",
                              "tinyapp", "--package", str(tmp_path / "src" / "tinyapp"), "--out", str(other)],
                             capture_output=True, text=True)
    assert refused.returncode != 0 and (other / "keep.txt").read_text(encoding="utf-8") == "mine"


def powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True)


def test_the_app_starts_from_a_program_of_its_own_named_like_it(tmp_path):
    done, out = bundle(tmp_path)
    assert done.returncode == 0, done.stderr
    info = powershell(f"$v = (Get-Item '{out / 'Tiny.exe'}').VersionInfo; $v.ProductName + '|' + $v.FileVersion + '|' + $v.CompanyName")
    assert info.stdout.strip() == "Tiny|2.3.1|Tiny Team"  # what Explorer and Task Manager show

    # Smart App Control blocks a new program until it is signed, so its code is run inside PowerShell,
    # which Microsoft signs: the same Python, started the same way.
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import bundle as tool
    finally:
        sys.path.pop(0)
    source = tmp_path / "host.cs"
    source.write_text(tool.host_source("Tiny", "tinyapp", "2.3.1", ""), encoding="utf-8")
    runtime = out / "runtime"

    def host(*args):
        quoted = ", ".join(f"'{a}'" for a in args)
        return powershell(f"Add-Type -TypeDefinition (Get-Content -Raw '{source}'); "
                          f"exit [Host]::Run('{runtime}', 'tinyapp', '{out / 'Tiny.exe'}', [string[]]@({quoted}))")

    ran = host("hello")
    assert ran.returncode == 0 and ran.stdout.strip() == "tiny ran hello", ran.stderr
    again = host("-m", "tinyapp", "again")  # a restart that names the module itself runs it once
    assert again.stdout.strip() == "tiny ran again", again.stderr
