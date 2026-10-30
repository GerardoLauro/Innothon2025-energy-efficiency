"""Locate CBC installed with PuLP, on PATH, or through CBC_PATH."""
import os
from pathlib import Path
import shutil

def ensure_cbc() -> Path:
    override = os.environ.get("CBC_PATH")
    if override:
        candidate = Path(override).expanduser()
        if not candidate.is_file():
            raise FileNotFoundError(f"CBC_PATH non valido: {candidate}")
        return candidate.resolve()
    command = shutil.which("cbc")
    if command:
        return Path(command)
    import pulp
    bundled = pulp.PULP_CBC_CMD(msg=False)
    if bundled.available():
        return Path(bundled.path)
    raise FileNotFoundError("CBC non disponibile: installalo separatamente oppure configura CBC_PATH.")

if __name__ == "__main__":
    print(ensure_cbc())
