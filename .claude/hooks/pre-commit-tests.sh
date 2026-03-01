#!/bin/bash
# Pre-commit hook: run skill tests before allowing git commit
COMMAND=$(jq -r '.tool_input.command' < /dev/stdin 2>/dev/null)

# Only trigger on git commit commands
if [[ "$COMMAND" =~ ^git\ commit ]]; then
  FAILED=0
  cd /root/jobs

  for skill_dir in skills/*/tests; do
    [ -d "$skill_dir" ] || continue
    skill=$(basename "$(dirname "$skill_dir")")

    PYTHONPATH="skills/$skill" BASEROW_URL=https://baserow.example.com BASEROW_TOKEN=test \
      python3 -m pytest "$skill_dir" -x -q --timeout=30 2>&1
    if [ $? -ne 0 ]; then
      echo "Tests FAILED in $skill" >&2
      FAILED=1
    fi
  done

  if [ $FAILED -ne 0 ]; then
    echo "Commit blocked: fix failing tests first." >&2
    exit 2
  fi
fi

exit 0
