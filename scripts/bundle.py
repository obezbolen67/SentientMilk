"""Build a Windows app folder that Smart App Control lets run.

A PyInstaller .exe is a new, unsigned program on every build, so Smart App Control blocks it.
This folder holds no new program: Python's own runtime (python.exe and its DLLs are signed by
the Python Software Foundation), the package files pip installed (the same bytes, so the same
reputation), the app's source, and a shortcut plus a .cmd that start it. Run this with the
Python whose packages the app uses, for example:

    python scripts/bundle.py --name SentientMilk --module sentientmilk_framework \
        --package sentientmilk_framework --requires "sentientmilk-framework[mcp]"
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import tomllib
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

MARK = "bundle.json"  # beside the runtime's python.exe; sentientmilk_framework.client.packaged() looks for it
STDLIB_SKIPPED = {"site-packages", "test", "idlelib", "tkinter", "turtledemo", "ensurepip", "__pycache__"}


def distributions(requirements: list) -> list:
    """The installed distributions these requirements need, with their dependencies (extras honoured)."""
    found, todo = {}, [r for r in map(Requirement, requirements) if r.marker is None or r.marker.evaluate({"extra": ""})]
    while todo:
        requirement = todo.pop()
        try:
            dist = metadata.distribution(requirement.name)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"{requirement.name} is not installed in {sys.executable}; install the app's "
                             "dependencies there first.")
        key, extras = canonicalize_name(dist.metadata["Name"]), set(requirement.extras)
        if key in found and extras <= found[key][1]:
            continue
        found.setdefault(key, (dist, set()))[1].update(extras)
        for line in dist.requires or []:
            dependency = Requirement(line)
            if dependency.marker is None or any(dependency.marker.evaluate({"extra": extra})
                                                for extra in found[key][1] | {""}):
                todo.append(dependency)
    return [dist for dist, _ in found.values()]


def editable(dist) -> bool:
    """An editable install points at a checkout: its code comes in with --package instead."""
    info = json.loads(dist.read_text("direct_url.json") or "{}")
    return bool(info.get("dir_info", {}).get("editable"))


def copy_tree(source: Path, target: Path, skipped=frozenset({"__pycache__"}), ignored=frozenset()) -> None:
    """``ignored``: paths under ``source`` to leave out, as git lists them (folders end in /)."""
    def leave_out(folder, names):
        here = Path(folder).relative_to(source).as_posix()
        prefix = "" if here == "." else here + "/"
        return [n for n in names if n in skipped or f"{prefix}{n}" in ignored or f"{prefix}{n}/" in ignored]

    shutil.copytree(source, target, ignore=leave_out, dirs_exist_ok=True)


def git_ignored(package: Path) -> frozenset:
    """What git ignores in a source package (local settings, keys, databases): none of it is the app's code."""
    try:
        listed = subprocess.run(["git", "-C", str(package), "ls-files", "--others", "--ignored", "--exclude-standard",
                                 "--directory", "-z"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return frozenset()  # not a checkout
    return frozenset(filter(None, listed.split("\0")))


def runtime(target: Path, dists: list) -> None:
    base = Path(sys.base_prefix)
    target.mkdir(parents=True)
    for item in base.iterdir():  # python.exe, pythonw.exe, python3XY.dll, vcruntime140*.dll
        if item.is_file() and (item.suffix == ".dll" or item.name in ("python.exe", "pythonw.exe")):
            shutil.copy2(item, target / item.name)
    copy_tree(base / "DLLs", target / "DLLs")
    copy_tree(base / "Lib", target / "Lib", STDLIB_SKIPPED)
    site = target / "Lib" / "site-packages"
    for dist in dists:
        if editable(dist):
            continue
        for file in dist.files or []:
            path = Path(file)
            if path.parts[0] == ".." or "__pycache__" in path.parts:  # console-script .exe launchers, data
                continue
            source = Path(dist.locate_file(file))
            if source.is_file():
                (site / path).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, site / path)
    # A ._pth file makes the runtime isolated: no PYTHONPATH, no user site-packages, no registry.
    (target / f"python{sys.version_info.major}{sys.version_info.minor}._pth").write_text(
        "Lib\nDLLs\nLib\\site-packages\n..\\app\nimport site\n", encoding="utf-8")


def launchers(out: Path, name: str, module: str, console: bool, icon: str) -> None:
    python = "python.exe" if console else "pythonw.exe"
    start = "" if console else 'start "" '
    (out / f"{name}.cmd").write_text(
        f'@{start}"%~dp0runtime\\{python}" -m {module} %*\r\n@exit /b %ERRORLEVEL%\r\n', encoding="utf-8")
    link = {"Path": str(out / f"{name}.lnk"), "Target": str(out / "runtime" / python), "Args": f"-m {module}",
            "Folder": str(out), "Icon": icon or str(out / "runtime" / python)}
    script = ("$l = ConvertFrom-Json $env:BUNDLE_LINK; $s = (New-Object -ComObject WScript.Shell).CreateShortcut($l.Path);"
              " $s.TargetPath = $l.Target; $s.Arguments = $l.Args; $s.WorkingDirectory = $l.Folder;"
              " $s.IconLocation = $l.Icon; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], check=True,
                   env={**os.environ, "BUNDLE_LINK": json.dumps(link)})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True, help="the app's name: NAME.lnk and NAME.cmd start it")
    parser.add_argument("--module", required=True, help="run as python -m MODULE")
    parser.add_argument("--package", action="append", default=[], help="a package folder of the app's source")
    parser.add_argument("--project", default="", help="the app's pyproject.toml: its dependencies are bundled "
                        "(read from the file: an editable install's metadata can be out of date)")
    parser.add_argument("--extra", action="append", default=[], help="an optional-dependencies group to bundle too")
    parser.add_argument("--requires", action="append", default=[], help="another requirement, e.g. 'requests'")
    parser.add_argument("--console", action="store_true", help="a console app (default: a window app, pythonw)")
    parser.add_argument("--icon", default="", help="an .ico for the shortcut")
    parser.add_argument("--out", default="", help="default: dist/windows/NAME")
    args = parser.parse_args(argv)
    out = Path(args.out or Path("dist") / "windows" / args.name).resolve()
    if out.exists():
        if not (out / "runtime" / MARK).exists():
            raise SystemExit(f"{out} is not a bundle this script made; move it away first.")
        try:
            shutil.rmtree(out)
        except OSError as exc:
            raise SystemExit(f"Could not replace {out} ({exc}). Close {args.name} if it runs from there.")
    requirements = list(args.requires)
    if args.project:
        project = tomllib.loads(Path(args.project).read_text(encoding="utf-8"))["project"]
        requirements += project.get("dependencies", [])
        for extra in args.extra:
            requirements += project.get("optional-dependencies", {})[extra]
    dists = distributions(requirements)
    runtime(out / "runtime", dists)
    for package in map(Path, args.package):
        copy_tree(package, out / "app" / package.name, ignored=git_ignored(package))
    icon = ""
    if args.icon:
        icon = str(out / Path(args.icon).name)
        shutil.copy2(args.icon, icon)
    (out / "runtime" / MARK).write_text(json.dumps({"name": args.name, "module": args.module}), encoding="utf-8")
    launchers(out, args.name, args.module, args.console, icon)
    check = subprocess.run([str(out / "runtime" / "python.exe"), "-c", f"import {args.module}"],
                           capture_output=True, text=True)
    if check.returncode:
        raise SystemExit(f"The bundle cannot import {args.module}:\n{check.stderr}")
    print(f"[bundle] {args.name}: {out} ({len(dists)} distributions)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
