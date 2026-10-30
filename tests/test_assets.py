import hashlib
import importlib.util
import json
import zipfile

import pytest


def load_restore(repository_root):
    spec = importlib.util.spec_from_file_location("restore_assets", repository_root / "scripts/restore_assets.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.restore


def test_verified_asset_restore_and_idempotency(tmp_path, repository_root):
    restore = load_restore(repository_root)
    data = b"synthetic asset"
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": [{"path": "data/a.txt", "bytes": len(data),
                         "sha256": hashlib.sha256(data).hexdigest()}]}))
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("data/a.txt", data)
    destination = tmp_path / "restored"
    assert restore(archive, destination, manifest) == 1
    assert restore(archive, destination, manifest) == 0
    assert (destination / "data/a.txt").read_bytes() == data


def test_restore_validates_every_hash_before_writing(tmp_path, repository_root):
    restore = load_restore(repository_root)
    manifest = tmp_path / "manifest.json"
    entries = [{"path": name, "bytes": 2, "sha256": hashlib.sha256(b"ok").hexdigest()}
               for name in ["data/a.txt", "data/b.txt"]]
    manifest.write_text(json.dumps({"files": entries}))
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w") as target:
        target.writestr("data/a.txt", b"ok")
        target.writestr("data/b.txt", b"no")
    destination = tmp_path / "restored"
    with pytest.raises(ValueError, match="checksum"):
        restore(archive, destination, manifest)
    assert not destination.exists()


def test_restore_rejects_external_path(tmp_path, repository_root):
    restore = load_restore(repository_root)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"files": [{"path": "../outside.txt", "bytes": 0, "sha256": ""}]}))
    archive = tmp_path / "assets.zip"
    with zipfile.ZipFile(archive, "w"):
        pass
    with pytest.raises(ValueError, match="Unsafe"):
        restore(archive, tmp_path / "restored", manifest)
