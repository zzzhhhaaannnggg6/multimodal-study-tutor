"""Collect license text for the bundled interpreter and PDF reader."""

from importlib.metadata import distribution
from pathlib import Path
import sys
import sysconfig


def notices() -> str:
    parts = ["Third-party notices for the local desktop preview\n",
             "Python " + sys.version + "\n" + Path(sysconfig.get_path("stdlib"), "LICENSE.txt").read_text()]
    for name in ("pypdf", "pyinstaller", "certifi", "pypdfium2", "Pillow"):
        package = distribution(name)
        parts.append(f"\n{name} {package.version}\n")
        for item in package.files or []:
            if "dist-info/licenses/" in str(item) or (any(token in item.name.lower() for token in ("license", "copying")) and "dist-info" in str(item)):
                raw = Path(package.locate_file(item)).read_bytes()
                try:
                    license_text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    license_text = raw.decode("latin-1")
                parts.append(f"\n{item.name}\n" + license_text)
    for license_file in sorted((Path(__file__).parent / "licenses").glob("*.txt")):
        parts.append(f"\nBundled runtime library: {license_file.stem}\n" + license_file.read_text())
    parts.append("\nmacOS system frameworks are provided by Apple and are not redistributed.\n")
    return "\n".join(parts)


if __name__ == "__main__":
    Path(sys.argv[1]).write_text(notices(), encoding="utf-8")
