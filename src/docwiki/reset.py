"""Explicit local reset, requiring exclusive access to the application's data directory."""

import argparse
import shutil

from filelock import Timeout

from docwiki.config import Settings
from docwiki.service import storage_lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="Confirm removal of local uploads/indexes"
    )
    args = parser.parse_args()
    root = Settings().data_dir.resolve()
    if not args.yes:
        raise SystemExit(
            f"This removes DocWiki data in {root}. Stop the server and rerun with --yes."
        )
    try:
        with storage_lock(root).acquire(timeout=0):
            # Only app-managed subdirectories, never arbitrary user files under DATA_DIR.
            for name in ("documents", "chroma"):
                path = root / name
                if path.is_symlink():
                    path.unlink()
                elif path.exists():
                    shutil.rmtree(path)
    except Timeout:
        raise SystemExit(
            "Stop the running DocWiki application before resetting its data."
        ) from None
    print("DocWiki uploads and indexes removed.")


if __name__ == "__main__":
    main()
