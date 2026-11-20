#!/usr/bin/env bash
# Run only offline checks; never connect to the household HA instance.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -x .venv/bin/python ]]; then
  export PATH="$PWD/.venv/bin:$PATH"
fi
git diff --check
git diff --cached --check
python - <<'CHECK'
import subprocess
from pathlib import PurePosixPath

paths = subprocess.check_output(["git", "ls-files", "-z"]).decode().split("\0")
for name in filter(None, paths):
    path = PurePosixPath(name)
    if path.suffix.lower() in {".apk", ".jks", ".keystore", ".pem", ".key"}:
        raise SystemExit(f"Private/binary artifact must not be tracked: {name}")
CHECK
ruff check .
ruff format --check .
mypy custom_components/myq tests
pytest
