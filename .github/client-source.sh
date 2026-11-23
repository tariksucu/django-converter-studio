#!/usr/bin/env bash
# The tests need the official Python client, converter-studio. Until it is on PyPI, install it
# from its public repository instead (tox reads CONVERTER_STUDIO_CLIENT).
set -euo pipefail
if python -m pip download --quiet --no-deps --dest "${RUNNER_TEMP:-/tmp}/client" \
  "converter-studio>=1.0,<2" 2>/dev/null; then
  echo "converter-studio comes from PyPI"
else
  echo "CONVERTER_STUDIO_CLIENT=git+https://github.com/tariksucu/converter-studio-python" \
    >>"$GITHUB_ENV"
  echo "converter-studio is not on PyPI yet: it comes from its repository"
fi
