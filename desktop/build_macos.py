"""Build a self-contained, ad-hoc signed LOCAL preview. Never a notarized release.

Run with a dedicated build venv containing requirements-build.txt. Only explicit
code/assets enter the bundle; no course workspace or developer environment.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def minimum_macos(backend: Path) -> str:
    versions = [(12, 0)]
    seen = set()
    for path in backend.rglob("*"):
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        with path.open("rb") as handle:
            magic = handle.read(4)
        if magic not in {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}:
            continue
        links = subprocess.check_output(["otool", "-L", str(path)], text=True)
        for line in links.splitlines()[1:]:
            dependency = line.strip().split(" (", 1)[0]
            if dependency.startswith("/") and not dependency.startswith(("/usr/lib/", "/System/Library/")):
                raise RuntimeError(f"Runtime still depends on an external developer library: {dependency}")
        load = subprocess.check_output(["otool", "-l", str(path)], text=True)
        values = re.findall(r"\bminos\s+([\d.]+)", load)
        values += re.findall(r"cmd LC_VERSION_MIN_MACOSX\s+cmdsize \d+\s+version ([\d.]+)", load)
        versions.extend(tuple(map(int, value.split("."))) for value in values)
    return ".".join(map(str, max(versions)))


def build(destination: Path) -> Path:
    if sys.platform != "darwin":
        raise SystemExit("The desktop preview currently builds on macOS only.")
    if destination.exists():
        raise SystemExit("Output already exists; choose a new --output directory to preserve it.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mst-desktop-", dir=destination.parent) as temporary:
        stage = Path(temporary)
        app = stage / "听课助手.app"
        contents = app / "Contents"
        resources = contents / "Resources"
        (contents / "MacOS").mkdir(parents=True)
        resources.mkdir()
        bundled_web = stage / "web"
        bundled_web.mkdir()
        for name in ("index.html", "app.js", "progress.js", "styles.css"):
            shutil.copy2(ROOT / "web" / name, bundled_web / name)
        run(sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--name", "study-backend", "--paths", ROOT / "src", "--hidden-import", "pypdf", "--hidden-import", "certifi",
            "--collect-all", "pypdfium2_raw", "--hidden-import", "pypdfium2", "--hidden-import", "PIL.Image",
            "--add-data", f"{bundled_web}:web", "--distpath", stage / "frozen",
            "--workpath", stage / "pyinstaller", "--specpath", stage, ROOT / "desktop/backend.py")
        shutil.move(stage / "frozen/study-backend", resources / "backend")
        minimum = minimum_macos(resources / "backend")
        run("xcrun", "swiftc", "-O", "-swift-version", "5", "-target", f"{platform.machine()}-apple-macosx{minimum}",
            ROOT / "desktop/StudyTutor.swift", "-o", contents / "MacOS/StudyTutor", "-framework", "AppKit", "-framework", "WebKit")
        with (contents / "Info.plist").open("wb") as handle:
            plistlib.dump({"CFBundleExecutable": "StudyTutor", "CFBundleIdentifier": "org.multimodal-study-tutor.desktop",
                          "CFBundleName": "听课助手", "CFBundleDisplayName": "听课助手",
                          "CFBundlePackageType": "APPL", "CFBundleShortVersionString": "0.2.0",
                          "CFBundleVersion": "1", "LSMinimumSystemVersion": minimum, "NSHighResolutionCapable": True,
                          "LSMultipleInstancesProhibited": True,
                          "NSHumanReadableCopyright": "MIT — Multimodal Study Tutor contributors"}, handle)
        (resources / "build-info.json").write_text(json.dumps({"architecture": platform.machine(), "minimum_macos": minimum,
                "built_on": platform.mac_ver()[0], "python": platform.python_version(), "signing": "ad-hoc", "notarized": False}, indent=2) + "\n")
        shutil.copy2(ROOT / "LICENSE", resources / "LICENSE.txt")
        # Notices list exact installed packages and their bundled license paths.
        run(sys.executable, ROOT / "desktop/third_party_notices.py", resources / "THIRD_PARTY_NOTICES.txt")
        run("codesign", "--force", "--deep", "--sign", "-", app)
        run("codesign", "--verify", "--deep", "--strict", app)
        destination.mkdir()
        shutil.move(app, destination / app.name)
    app = destination / "听课助手.app"
    archive = destination / f"study-tutor-macos-{minimum}-{platform.machine()}-preview.zip"
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, archive)
    with archive.open("rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    (destination / "SHA256SUMS.txt").write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"Local preview: {app}")
    print("Ad-hoc signed only; not Developer ID signed or notarized.")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/macos-preview")
    build(parser.parse_args().output.resolve())
