#!/usr/bin/env python3
"""Restore only original manifest-listed assets, after verifying all hashes."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import zipfile


def restore(archive: Path, destination: Path, manifest_path: Path, overwrite=False) -> int:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    destination = destination.resolve()
    pending = []
    with zipfile.ZipFile(archive) as source:
        for entry in manifest["files"]:
            rel = PurePosixPath(entry["path"])
            if rel.is_absolute() or ".." in rel.parts or "\\" in str(rel) or ":" in str(rel):
                raise ValueError("Unsafe asset path in manifest")
            target = (destination / Path(*rel.parts)).resolve()
            if not target.is_relative_to(destination):
                raise ValueError("Asset path escapes destination")
            content = source.read(str(rel))
            if len(content) != entry["bytes"] or hashlib.sha256(content).hexdigest() != entry["sha256"]:
                raise ValueError(f"Asset checksum mismatch: {rel}")
            if target.exists():
                if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == entry["sha256"]:
                    continue
                if not overwrite:
                    raise FileExistsError(f"Refusing to overwrite: {target}; use --overwrite explicitly")
            pending.append((target, content))
        # Validation completes before any writes, including overwrite checks.
        for target, content in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    return len(pending)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args(argv)
    manifest = Path(__file__).resolve().parents[1] / "data/asset-manifest.json"
    count = restore(args.archive, args.destination, manifest, args.overwrite)
    print(f"Restored {count} original assets; these paths remain ignored by Git.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
