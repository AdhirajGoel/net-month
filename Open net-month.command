#!/bin/bash
cd "$(dirname "$0")" || exit 1
for budget_python in .venv/bin/python3 python3; do
  if command -v "$budget_python" >/dev/null 2>&1 && "$budget_python" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; then
    "$budget_python" budget_server.py "$@"
    budget_result=$?
    if [ "$budget_result" -ne 0 ] && [ -t 0 ]; then read -r -p 'Press Return to close.'; fi
    exit "$budget_result"
  fi
done
printf '%s\n' 'Python 3.9 or newer is required. Follow the README setup instructions.'
if [ -t 0 ]; then read -r -p 'Press Return to close.'; fi
exit 1
