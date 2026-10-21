"""PyInstaller entry; keep the normal CLI and library unchanged."""

from mst.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
