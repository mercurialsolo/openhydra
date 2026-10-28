"""Stage demo for "Beyond Agent Accuracy": a synthetic fleet on the real engine.

    python -m bench.hydrabench.demo fleet [--auto] [--agents 4]
    python -m bench.hydrabench.demo bench --recovery 0|1 [--claims crash_recovery ...] [--auto]

``fleet`` runs N agents as back-to-back workflows on a real OpenHydra engine
(SQLite, mailbox, events) with a mock LLM, injects four failures on a timer, and
runs a watcher that notes each one down as an incident (stdout and
``incidents.jsonl``), naming the HydraBench scenario it corresponds to:

    t+6s   process death: every in-flight run orphaned, then recovered   (cr-1)
    t+14s  a step that hangs past twice the usual length                  (v2: hang)
    t+22s  runs that COMPLETE and emit nothing                            (v2: throughput)
    t+30s  a step cost that blows through a $1 cap the engine ignores     (cc-1)

``bench`` runs real HydraBench scenarios one at a time, printing each result as
it lands. ``--recovery 0`` measures the engine without ``recover_workflow``
(v1.1); ``--recovery 1`` with it (v1.2).

Everything prints as one line per event, for a projector: no screen redraws.
The executor knobs the demo needs live in a subclass here, so the adapter that
produced the committed result files is untouched.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from .frameworks.openhydra_adapter import MockRoleExecutor, OpenHydraAdapter

BOLD, DIM, RED, ORANGE, BLUE, GREEN, RESET = (
    "\033[1m", "\033[2m", "\033[31m", "\033[33m", "\033[34m", "\033[32m", "\033[0m",
)
T0 = time.monotonic()


def clock() -> str:
    return f"{DIM}{time.monotonic() - T0:5.1f}s{RESET}"


def say(line: str) -> None:
    print(f"{clock()}  {line}", flush=True)


class DemoExecutor(MockRoleExecutor):
    """The adapter's mock, plus the knobs the injections need.

    Read from the workflow config: ``demo_hang_seconds`` (one step sleeps this
    long), ``demo_empty_output`` (steps complete and emit nothing).
    """

    async def execute(self, role_id, instructions, context=None, messages=None, store_memory=False, **_):
        from openhydra.agents.base import SessionResult

        cfg = (context or {}).get("workflow_config") or {}
        seconds = float(cfg.get("mock_step_seconds", 0.6))
        if cfg.get("demo_hang_seconds") and instructions.endswith("step 2"):
            seconds = float(cfg["demo_hang_seconds"])
        cost = float(cfg.get("step_cost_usd", 0.01))
        self.calls += 1
        await asyncio.sleep(seconds)
        emitted = 0 if cfg.get("demo_empty_output") else 1
        return SessionResult(
            output={"text": "" if not emitted else "mock output", "emitted": emitted, "quality_score": 30},
            raw_text="mock output" if emitted else "",
            tokens_used=100,
            cost_usd=cost,
        )


class Fleet:
    def __init__(self, adapter: OpenHydraAdapter, n_agents: int, out_dir: Path) -> None:
        self.adapter = adapter
        self.agents = [f"agent-{i + 1}" for i in range(n_agents)]
        self.wf_agent: dict[str, str] = {}          # workflow id -> agent
        self.wf_cfg: dict[str, dict[str, Any]] = {}  # workflow id -> config
        self.live: dict[str, asyncio.Task] = {}      # workflow id -> execution task
        self.next_cfg: dict[str, list[dict[str, Any]]] = {a: [] for a in self.agents}
        self.step_started: dict[str, float] = {}     # step id -> monotonic
        self.step_durations: list[float] = []
        self.steps_done: dict[str, int] = {}
        self.crashed = asyncio.Event()
        self.crashed.set()  # set = running; clear = dead
        self.incidents: dict[str, dict[str, Any]] = {}
        self.incident_file = out_dir / "incidents.jsonl"
        self.incident_file.write_text("")
        self.stop = False

    # -- the agents --------------------------------------------------------

    async def agent_loop(self, agent: str) -> None:
        n = 0
        while not self.stop:
            await self.crashed.wait()
            n += 1
            cfg = self.next_cfg[agent].pop(0) if self.next_cfg[agent] else {}
            steps = [{"role_id": "planner", "instructions": f"{agent} run {n} step {i}"} for i in range(4)]
            for i in range(1, 4):
                steps[i]["depends_on"] = [i - 1]
            wf = await self.adapter.create_workflow(steps, config=cfg or None)
            self.wf_agent[wf] = agent
            self.wf_cfg[wf] = cfg
            task = asyncio.create_task(self.adapter._engine.execute_workflow(wf))
            self.live[wf] = task
            try:
                await task
            except asyncio.CancelledError:
                continue
            except Exception as e:  # noqa: BLE001
                say(f"{RED}{agent} loop error: {e!r}{RESET}")
            finally:
                self.live.pop(wf, None)
            await asyncio.sleep(1.0)

    def on_event(self, ev: Any) -> None:
        d = ev.data or {}
        wf = d.get("workflow_id", "")
        agent = self.wf_agent.get(wf, "?")
        t = ev.type
        if t == "step.started":
            self.step_started[d.get("step_id", "")] = time.monotonic()
        elif t == "cost.updated":
            sid = d.get("step_id", "")
            if sid in self.step_started:
                self.step_durations.append(time.monotonic() - self.step_started.pop(sid))
            self.steps_done[wf] = self.steps_done.get(wf, 0) + 1
        elif t == "workflow.completed":
            say(f"{DIM}{agent:8}{RESET} {GREEN}COMPLETED{RESET}  {self.steps_done.get(wf, 0)} steps  ${d.get('cost_usd', 0):.2f}")
        elif t == "workflow.failed":
            say(f"{DIM}{agent:8}{RESET} {RED}FAILED{RESET}     {d.get('error', '')}")
        elif t == "workflow.paused" and d.get("paused_by") == "recovery":
            say(f"{DIM}{agent:8}{RESET} {BLUE}recovered{RESET}  {d.get('requeued_steps', 0)} step re-queued")

    # -- the injections ----------------------------------------------------

    async def inject(self) -> None:
        await asyncio.sleep(6)
        # land the kill while runs are in flight, not in the pause between runs
        for _ in range(100):
            if len(self.live) >= max(2, len(self.agents) // 2) and self.step_started:
                break
            await asyncio.sleep(0.05)
        await asyncio.sleep(0.3)
        say(f"{BOLD}{RED}>>> kill -9: the process running every agent dies. Database survives.{RESET}")
        self.crashed.clear()
        orphaned = list(self.live)
        for task in list(self.live.values()):
            task.cancel()
        await asyncio.sleep(0.05)
        self.adapter._engine = self.adapter._new_engine()
        self.adapter._engine_events_hook()
        await asyncio.sleep(4)
        say(f"{BOLD}{BLUE}>>> supervisor restarts the process; recover_workflow on every orphaned run{RESET}")
        for wf in orphaned:
            try:
                task = await self.adapter._engine.recover_workflow(wf)
                self.live[wf] = task
                task.add_done_callback(lambda _t, w=wf: self.live.pop(w, None))
            except ValueError as e:
                say(f"{RED}recovery refused for {self.wf_agent.get(wf)}: {e}{RESET}")
        self.crashed.set()

        await asyncio.sleep(4)
        say(f"{BOLD}{ORANGE}>>> agent-2's next run: step 2 hangs for 10 s. It never fails.{RESET}")
        self.next_cfg["agent-2"].append({"demo_hang_seconds": 10})

        await asyncio.sleep(8)
        say(f"{BOLD}{ORANGE}>>> agent-3's next two runs complete every step and emit nothing.{RESET}")
        self.next_cfg["agent-3"] += [{"demo_empty_output": True}, {"demo_empty_output": True}]

        await asyncio.sleep(8)
        say(f"{BOLD}{ORANGE}>>> agent-4's next run: $0.50 a step, 4 steps, budget_usd 1.00 in the config.{RESET}")
        self.next_cfg["agent-4"].append({"step_cost_usd": 0.50, "budget_usd": 1.00})

        await asyncio.sleep(10)
        self.stop = True

    # -- the watcher ---------------------------------------------------------

    def note(self, key: str, agent: str, cls: str, bench: str, detail: str, needs: str) -> None:
        if key in self.incidents:
            return
        rec = {"t": round(time.monotonic() - T0, 1), "agent": agent, "class": cls,
               "hydrabench": bench, "detail": detail, "needs": needs, "resolved_t": None}
        self.incidents[key] = rec
        with self.incident_file.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        say(f"{BOLD}{ORANGE}INCIDENT{RESET} {agent:8} {BOLD}{cls}{RESET}  {detail}  {DIM}[{bench}] needs: {needs}{RESET}")

    def resolve(self, key: str) -> None:
        rec = self.incidents.get(key)
        if rec and rec["resolved_t"] is None:
            rec["resolved_t"] = round(time.monotonic() - T0, 1)
            with self.incident_file.open("a") as f:
                f.write(json.dumps({**rec, "event": "resolved"}) + "\n")
            say(f"{BOLD}{GREEN}RESOLVED{RESET} {rec['agent']:8} {rec['class']}")

    async def watcher(self) -> None:
        usual = 0.4
        empty_streak: dict[str, int] = {}
        while not self.stop:
            await asyncio.sleep(0.5)
            if self.step_durations:
                s = sorted(self.step_durations)
                usual = max(0.2, s[len(s) // 2])
            db = self.adapter._db.conn
            cur = await db.execute(
                "SELECT w.id, w.status, s.id, s.status, s.started_at, s.cost_usd, s.output_data "
                "FROM workflows w JOIN steps s ON s.workflow_id = w.id"
            )
            rows = await cur.fetchall()
            by_wf: dict[str, list[Any]] = {}
            for r in rows:
                by_wf.setdefault(r[0], []).append(r)
            for wf, steps in by_wf.items():
                agent = self.wf_agent.get(wf, "?")
                cfg = self.wf_cfg.get(wf, {})
                wstatus = steps[0][1]
                running = [s for s in steps if s[3] == "running"]
                # 1. orphaned: a RUNNING step with no live task in this process
                if running and wf not in self.live:
                    self.note(f"orphan:{wf}", agent, "orphaned run",
                              "cr-1 crash recovery",
                              f"step RUNNING in the database, no process running it",
                              "a restart with recover_workflow")
                elif wf in self.live or wstatus in ("completed", "failed"):
                    self.resolve(f"orphan:{wf}")
                # 2. overlong: a running step older than 2x usual (only for runs this process owns)
                if wstatus in ("completed", "failed"):
                    self.resolve(f"hang:{wf}")
                for s in (running if wf in self.live else []):
                    age = time.monotonic() - self.step_started.get(s[2], time.monotonic())
                    if age > 2 * usual and age > 1.5:
                        self.note(f"hang:{wf}", agent, "overlong run",
                                  "v2 hang detection (no v1 scenario)",
                                  f"step running {age:.1f}s, {age / usual:.0f}x the usual {usual:.1f}s; status says executing",
                                  "a stuck verdict, then a kill that is real")
                # 3. completed with nothing emitted
                if wstatus == "completed":
                    emitted = 0
                    for s in steps:
                        try:
                            emitted += int((json.loads(s[6] or "{}") or {}).get("emitted", 1))
                        except Exception:
                            emitted += 1
                    k = f"empty:{wf}"
                    if emitted == 0 and k not in self.incidents:
                        empty_streak[agent] = empty_streak.get(agent, 0) + 1
                        self.incidents[k] = {"resolved_t": 0}  # count once
                        if empty_streak[agent] >= 2:
                            self.note(f"noop:{agent}", agent, "ran, produced nothing",
                                      "v2 throughput liveness (no v1 scenario)",
                                      f"{empty_streak[agent]} runs COMPLETED, 0 outputs; status healthy",
                                      "a reader that counts outputs, not completions")
                # 4. spend past the cap
                budget = cfg.get("budget_usd")
                if budget:
                    spent = sum(float(s[5] or 0) for s in steps)
                    if spent > budget:
                        self.note(f"budget:{wf}", agent, "spend past cap",
                                  "cc-1 hard spend cap",
                                  f"${spent:.2f} spent against budget_usd {budget:.2f}; the engine did not stop",
                                  "a workflow-level cap in the engine (not shipped)")


def _hook_events(adapter: OpenHydraAdapter, fleet: Fleet) -> None:
    async def handler(ev: Any) -> None:
        try:
            fleet.on_event(ev)
        except Exception as e:  # noqa: BLE001
            say(f"{RED}event handler error: {e!r}{RESET}")
    adapter._events.on_all(handler)


async def run_fleet(args: argparse.Namespace) -> None:
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    adapter = OpenHydraAdapter()
    say("setting up a real OpenHydra engine: SQLite, mailbox, events, mock LLM ...")
    await adapter.setup()
    adapter._executor = DemoExecutor()
    adapter._engine = adapter._new_engine()
    adapter._engine_events_hook = lambda: None
    fleet = Fleet(adapter, args.agents, out_dir)
    _hook_events(adapter, fleet)
    say(f"{BOLD}ready.{RESET} {args.agents} agents, 4 steps each, back to back. incidents -> {fleet.incident_file}")
    if not args.auto:
        await asyncio.get_event_loop().run_in_executor(None, lambda: input("press Enter to start the fleet "))
    tasks = [asyncio.create_task(fleet.agent_loop(a)) for a in fleet.agents]
    tasks.append(asyncio.create_task(fleet.watcher()))
    def _report(t: asyncio.Task) -> None:
        if not t.cancelled() and t.exception():
            say(f"{RED}task died: {t.exception()!r}{RESET}")
    for t in tasks:
        t.add_done_callback(_report)
    await fleet.inject()
    await asyncio.sleep(1)
    for t in tasks:
        t.cancel()
    say(f"{BOLD}done.{RESET} incidents noted: {sum(1 for v in fleet.incidents.values() if 'class' in v)}")
    for rec in fleet.incidents.values():
        if "class" in rec:
            say(f"  {rec['t']:5.1f}s {rec['agent']:8} {rec['class']:22} [{rec['hydrabench']}]"
                + (f"  resolved {rec['resolved_t']}s" if rec["resolved_t"] else ""))
    await adapter.teardown()


async def run_bench(args: argparse.Namespace) -> None:
    os.environ["HYDRABENCH_RECOVERY"] = str(args.recovery)
    from .config import Claim, scenarios_for_claim
    from .runner import CLAIM_RUNNERS

    adapter = OpenHydraAdapter()
    say(f"setting up OpenHydra for HydraBench, recovery={'on (v1.2)' if args.recovery else 'off (v1.1)'} ...")
    await adapter.setup()
    claims = [Claim(c) for c in args.claims] if args.claims else list(Claim)
    say(f"{BOLD}ready.{RESET} {sum(len(scenarios_for_claim(c)) for c in claims)} scenarios x {args.runs} runs")
    if not args.auto:
        await asyncio.get_event_loop().run_in_executor(None, lambda: input("press Enter to run "))
    totals: dict[str, list[float]] = {}
    try:
        for claim in claims:
            for sc in scenarios_for_claim(claim):
                scores = []
                for run in range(args.runs):
                    r = await CLAIM_RUNNERS[claim](adapter, sc, run)
                    scores.append(r.score)
                    m = {k: v for k, v in r.metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
                    brief = ", ".join(f"{k}={v:g}" for k, v in list(m.items())[:3])
                    colour = GREEN if r.score >= 100 else (ORANGE if r.score > 0 else RED)
                    say(f"{sc.id:5} {sc.name[:34]:34} {colour}{r.score:5.1f}{RESET}  {DIM}{brief}{RESET}"
                        + (f"  {DIM}{r.notes}{RESET}" if r.notes else ""))
                totals.setdefault(claim.value, []).extend(scores)
    finally:
        await adapter.teardown()
    say(f"{BOLD}per claim:{RESET} " + "  ".join(f"{c} {sum(v) / len(v):.1f}" for c, v in totals.items()))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fleet")
    f.add_argument("--agents", type=int, default=4)
    f.add_argument("--auto", action="store_true", help="no Enter prompt")
    f.add_argument("--out", default="bench/demo-out")
    b = sub.add_parser("bench")
    b.add_argument("--recovery", type=int, choices=(0, 1), default=1)
    b.add_argument("--claims", nargs="*", default=["crash_recovery"])
    b.add_argument("--runs", type=int, default=1)
    b.add_argument("--auto", action="store_true")
    args = p.parse_args()
    if args.cmd == "fleet":
        asyncio.run(run_fleet(args))
    else:
        asyncio.run(run_bench(args))


if __name__ == "__main__":
    main()
