# Coding Principles

## Purpose
Enforce clean, maintainable code practices across all engineering sessions.

## Principles

### 1. Simplicity First
- Single responsibility per function/class
- No premature abstractions
- Choose the boring solution over the clever one
- If you need to explain it, it's too complex

### 2. Test-Driven
- Write test first (red), implement (green), refactor
- Test behavior, not implementation
- One assertion per test when practical
- Tests must be deterministic

### 3. Incremental Progress
- Small changes that compile and pass tests
- One feature per session
- Commit working code frequently
- Leave codebase in mergeable state

### 4. Clear Intent
- Descriptive names over comments
- Explicit data flow and dependencies
- Type annotations where the language supports them
- Error messages that help debugging

### 5. Scope Discipline
- Only implement what was requested
- No drive-by improvements
- No refactoring outside current feature scope
- No error handling for impossible scenarios

## DO NOT
- Start implementing without understanding success criteria
- Make silent assumptions about ambiguous requirements
- Add features or abstractions not requested
- Build for hypothetical future requirements
- Fix typos, reformat code, or make cosmetic changes outside scope

## Escalation Triggers
Escalate to human if:
- Requirements are unclear or conflicting
- Feature requires architectural decision not in scope
- Dependencies are missing and can't be resolved
- Three consecutive attempts without progress
