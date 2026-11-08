"""Seed an empty persistent data volume before starting the web server."""

import os
from pathlib import Path
import shutil
from tempfile import NamedTemporaryFile


def seed_data(seed_dir: Path, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for name in ("catalog.json", "tours.json", "tickets.json"):
        destination = data_dir / name
        if destination.exists():
            continue
        temporary = None
        try:
            with NamedTemporaryFile(dir=data_dir, prefix=f".{name}.", delete=False) as target, (seed_dir / name).open("rb") as source:
                temporary = Path(target.name)
                shutil.copyfileobj(source, target)
            os.link(temporary, destination)
        except FileExistsError:
            continue
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[1]
    seed_data(root / "seed-data", root / "data")
    os.execvp("python", [
        "python", "-m", "uvicorn", "backend.app:app",
        "--host", "0.0.0.0", "--port", "8765", "--no-access-log",
    ])
