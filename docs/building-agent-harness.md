# Building an agent harness that doesn't die

## Abstract

This is a technical note about what it actually takes to build multi-agent orchestration where LLM agents use real tools (filesystem, browser, shell, external APIs) autonomously over long-running sessions. It comes from building OpenHydra, a single-process, local-first agent harness. Five problems dominate the work: crash recovery, secret containment, inter-agent communication, subprocess lifecycle, and channel security. Most of what we share here is plumbing. The agent orchestration part is maybe 20% of the effort.

---

## 1. Agents die. Plan for it.

The hardest operational problem isn't prompt engineering. It's that agents crash, time out, and produce garbage. A subprocess running `claude --print` might hang for 40 minutes in a bad tool loop. The host process might get OOM-killed. The machine might restart mid-workflow.

Our answer is write-ahead state. Every workflow state transition writes to SQLite *before* execution begins. Steps go `PENDING -> RUNNING -> COMPLETED|FAILED`. On startup, the engine queries for workflows stuck in `EXECUTING` with steps stuck in `RUNNING`, resets those steps to `PENDING`, and re-runs them:

```python
# Auto-resume interrupted workflows on restart
cursor = await self.db.conn.execute(
    "SELECT id FROM workflows WHERE status = ?",
    (WorkflowStatus.EXECUTING.value,),
)
for row in rows:
    await self.db.conn.execute(
        "UPDATE steps SET status = ?, error = NULL "
        "WHERE workflow_id = ? AND status = ?",
        (StepStatus.PENDING.value, wf_id, StepStatus.RUNNING.value),
    )
```

The agent subprocess gets a hard 1-hour timeout via `asyncio.wait_for`. If it hangs, we kill it, record the failure, and the retry loop (up to `max_retries_per_step`) tries again. A concurrency semaphore (`asyncio.Semaphore(max_concurrent)`) keeps runaway agent spawning from eating all system resources.

Treat agent sessions like database transactions. If you can't prove it completed, assume it didn't.

## 2. Secrets leak through environment variables

When you spawn a subprocess that inherits `os.environ`, it inherits every API key, OAuth token, and service credential in the parent. An agent with shell access can run `echo $ANTHROPIC_API_KEY` and pull it out through its own output.

We maintain an explicit denylist of sensitive environment variables stripped from child processes:

```python
_SENSITIVE_ENV_KEYS = {
    "CLAUDECODE", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN", "OPENHYDRA_WEB_API_KEY",
    "OPENHYDRA_SLACK_BOT_TOKEN", "OPENHYDRA_DISCORD_BOT_TOKEN",
    "OPENHYDRA_WHATSAPP_ACCESS_TOKEN", "TAVILY_API_KEY",
    "PERPLEXITY_API_KEY",
}
```

This applies at two layers: the filesystem tool router (which runs Bash commands for the Anthropic API provider) and the Claude SDK provider (which spawns the CLI subprocess). The CLI provider has a subtle wrinkle. When the parent process has `CLAUDE_CODE_OAUTH_TOKEN` set, we also strip `ANTHROPIC_API_KEY` to prevent the child from picking up a stale key instead of using the valid OAuth flow. We found this one the hard way.

Filesystem tools also enforce `restrict_to_cwd=True` and block destructive shell patterns (`rm -rf /`, `curl | sh`, `dd of=/dev/`) via regex. This is defense in depth, not a guarantee. But it catches the common accidental and prompt-injected exfiltration vectors.

## 3. Agents need to talk to each other, not just to you

A workflow where the planner produces a plan, the engineer writes code, and the test agent validates it requires those agents to exchange structured information. Passing everything through prompt context doesn't scale. Context windows fill up and you lose the ability to route messages selectively.

We built two communication primitives:

**Mailbox.** A SQLite-backed message queue where steps send messages to specific other steps, or broadcast. Messages are persisted, timestamped, and marked read when consumed. The receiving agent gets unread messages injected into its system prompt before execution.

**Workspace.** A per-workflow shared directory where agents produce and consume file artifacts. Files are tracked by content hash for change detection, and artifact events propagate through the event bus so observers (UIs, logging, channels) stay informed.

The important thing is that both are *durable*. If the engineer agent crashes after writing a file but before the test agent runs, the workspace still has the artifact on disk. The mailbox still has the message in SQLite. Recovery works because communication state survives independently of agent state.

## 4. Channels are untrusted

OpenHydra exposes a REST+WebSocket API and supports Slack, Discord, WhatsApp, and email. Each channel is a potential attack surface. A compromised Slack bot token shouldn't give the attacker full engine access.

We handle this with `RestrictedEngine`, a security proxy that wraps the real engine and enforces per-channel permission flags:

```python
class RestrictedEngine:
    async def submit(self, task, **kwargs):
        if not self._permissions.can_submit:
            raise PermissionError(...)
        self._check_rate_limit()
        return await self._engine.submit(task, **kwargs)
```

Each channel gets its own permission set: can it submit tasks? Read status? Access the database? Emit events? A sliding-window rate limiter prevents abuse (configurable submissions per hour). The `__getattr__` fallback denies access to any engine attribute not explicitly exposed. The event bus proxy allows subscription but blocks emission. Channels can observe but not forge engine events.

The web API layer adds bearer token and API key authentication, with explicit carve-outs only for health checks and auth endpoints.

## 5. Skills are code, and code is dangerous

Agents that pick up new capabilities at runtime via dynamically generated skills are running code they wrote themselves. Our `SkillBuilder` generates skills on-the-fly via LLM when a requested skill isn't found on disk. Every generated skill passes through a three-stage security pipeline before it can execute:

1. **Static analysis** -- scan for dangerous patterns (shell injection, network access, file system escapes)
2. **Sandbox execution** -- run the skill in a restricted environment and observe behavior
3. **LLM review** -- a separate agent evaluates the skill for safety

Skills below a risk threshold auto-approve. Everything above requires human approval, surfaced as events that any connected UI can present. Bundled skills (shipped with the project) skip the pipeline. They're already trusted.

There's something unsettling about agents writing their own tools and then using them. The pipeline doesn't make that feeling go away, but it does mean there's a paper trail and a human chokepoint.

## What we'd tell someone starting this work

The agent orchestration part, the DAGs, role assignment, prompt assembly, that's maybe 20% of the effort. The other 80% is plumbing. Making subprocesses not hang. Making state survive crashes. Making secrets not leak. Making untrusted channels not escalate. Making 685 tests cover all of it deterministically.

The boring architectural choices were the right ones. SQLite for everything: state, messages, memory, approvals. Protocol classes instead of inheritance. Events for decoupling. Single process, no Docker, no external services. Every component testable in isolation with a fresh in-memory database.

If your agents can't survive a `kill -9`, can't talk to each other across crashes, and can't be connected to Slack without risking your API keys, you don't have a harness. You have a demo.
