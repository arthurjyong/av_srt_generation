from __future__ import annotations

import subprocess
from typing import Sequence


def run_command(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """Run a subprocess command and return the completed process.

    Raises a RuntimeError with a helpful message if the command fails or
    cannot be found.
    """

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:  # pragma: no cover - exercised in tests
        raise RuntimeError(
            f"Command not found: {command[0]}. Is it installed and on PATH?"
        ) from exc

    if result.returncode != 0:
        stderr = result.stderr.strip()
        stdout = result.stdout.strip()
        output = stderr or stdout
        raise RuntimeError(f"Command failed ({command[0]}): {output}")

    return result
