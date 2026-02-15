# Engineering Harness

## Purpose
Structured pattern for long-running engineering work across multiple sessions.

## Harness Files

### progress log (`claude-progress.txt`)
Append-only session log. Each session writes:
```
=== Session YYYY-MM-DD HH:MM ===
Goals:
- What this session aims to accomplish

Actions Taken:
- What was done

Outcomes:
- What was achieved

Blockers:
- What couldn't be resolved

Next Steps:
- What the next session should do
=== End Session ===
```

### feature list (`feature_list.json`)
```json
{
  "features": [
    {
      "id": "feat-001",
      "description": "Feature description",
      "passes": false,
      "test_command": "pytest tests/test_feature.py",
      "acceptance_criteria": ["Criterion 1", "Criterion 2"],
      "artifacts": []
    }
  ]
}
```

### init script (`init.sh`)
Idempotent bootstrap that installs deps and runs smoke tests.

## Session Flow

1. **Get bearings**: Read progress log, feature list, recent git log
2. **Run init**: Execute init.sh to verify environment
3. **Pick one feature**: Choose the next `passes: false` feature
4. **Implement**: Write code + tests for that one feature only
5. **Verify**: Run the feature's test command
6. **Update**: Set `passes: true` if tests pass
7. **Log**: Append session entry to progress log
8. **Commit**: Clean commit with descriptive message

## Rules
- ONE feature per session — no multi-feature attempts
- Always read progress log before starting work
- Never edit feature descriptions or acceptance criteria
- Never mark `passes: true` without running tests
- Always leave codebase in committable state
- End every session with a git commit

## Escalation Triggers
- Three consecutive sessions without flipping any `passes` flag
- Test failures that can't be resolved in current session
- Acceptance criteria are unclear or conflicting
- Feature requires architectural decision
