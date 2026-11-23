"""Offline validation of the actual installed dependencies and local config."""

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import os
import sys

from packaging.requirements import Requirement
from dotenv import load_dotenv


def verify_requirements(file: Path) -> None:
    for line in file.read_text().splitlines():
        line = line.strip().rstrip("\\").strip()
        if not line or line.startswith(("#", "--")):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            raise RuntimeError(
                f"{requirement.name} is missing; run npm run setup."
            ) from None
        if installed not in requirement.specifier:
            raise RuntimeError(
                f"{requirement.name}=={installed} does not satisfy {requirement}; regenerate the lockfile and run npm run setup."
            )


def main():
    backend = Path(__file__).resolve().parents[1]
    for name in ("requirements.txt", "requirements.in"):
        verify_requirements(backend / name)
    load_dotenv(os.environ.get("CORTEX_ENV_FILE", backend.parent / ".env"))
    import app.main  # noqa: F401 -- exercise the real import boundary
    from app.security import validate_encryption_keys

    validate_encryption_keys()


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
