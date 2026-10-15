"""Bounded, policy-first educational agent orchestration primitives.

This is a pure core component: no HTTP routes, database writes or model calls.
Callers must provide a server-authoritative authorization function and durable
audit/persistence adapters before using it for real campus workflows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Mapping, Any
import asyncio
import uuid


class Decision(str, Enum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


class TaskStatus(str, Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Scope:
    campus_id: str
    learner_id: str
    educator_id: str


@dataclass(frozen=True)
class Evidence:
    source_id: str
    summary: str


@dataclass(frozen=True)
class Recommendation:
    text: str
    evidence: tuple[Evidence, ...]
    proposal_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass(frozen=True)
class Result:
    task: str
    status: TaskStatus
    value: Any = None
    error: str | None = None


Agent = Callable[[Scope, Mapping[str, Result]], Awaitable[Any]]
Authorize = Callable[[Scope, str], Awaitable[bool]]
Audit = Callable[[Scope, str, str], Awaitable[None]]


class GovernedOrchestrator:
    """Deterministic DAG executor with server-side authorization at each step.

    Does not infer authorization from a prompt, agent output, or client claims.
    Each task's dependencies must be previously completed, and a failure blocks
    dependent work. Parallelism is bounded. Audit failure stops the operation.
    """

    def __init__(self, authorize: Authorize, audit: Audit, *, max_parallel: int = 3):
        if not 1 <= max_parallel <= 8:
            raise ValueError("max_parallel must be between 1 and 8")
        self.authorize, self.audit = authorize, audit
        self.max_parallel = max_parallel

    async def run(
        self,
        scope: Scope,
        tasks: Mapping[str, tuple[tuple[str, ...], Agent]],
    ) -> dict[str, Result]:
        if not all((scope.campus_id, scope.learner_id, scope.educator_id)):
            raise ValueError("immutable scope identifiers required")
        pending = dict(tasks)
        results: dict[str, Result] = {}
        if not pending:
            return results
        if any(dep not in tasks for deps, _ in tasks.values() for dep in deps):
            raise ValueError("unknown task dependency")
        while pending:
            ready = sorted(
                name for name, (deps, _) in pending.items()
                if all(dep in results for dep in deps)
            )
            if not ready:
                raise ValueError("cyclic task dependency")
            batch = ready[: self.max_parallel]

            async def execute(name: str) -> Result:
                deps, agent = pending[name]
                if any(results[dep].status != TaskStatus.SUCCEEDED for dep in deps):
                    await self.audit(scope, name, "blocked:dependency")
                    return Result(name, TaskStatus.BLOCKED, error="dependency failed")
                if not await self.authorize(scope, name):
                    await self.audit(scope, name, "blocked:authorization")
                    return Result(name, TaskStatus.BLOCKED, error="not authorized")
                await self.audit(scope, name, "started")
                try:
                    value = await agent(scope, {dep: results[dep] for dep in deps})
                except Exception:
                    await self.audit(scope, name, "failed")
                    return Result(name, TaskStatus.FAILED, error="agent execution failed")
                await self.audit(scope, name, "succeeded")
                return Result(name, TaskStatus.SUCCEEDED, value=value)

            outcomes = await asyncio.gather(*(execute(name) for name in batch))
            for outcome in outcomes:
                results[outcome.task] = outcome
                del pending[outcome.task]
        return results


async def review_recommendation(
    scope: Scope,
    proposal: Recommendation,
    decision: Decision,
    *,
    authorize: Authorize,
    persist: Callable[[Scope, Recommendation, Decision], Awaitable[None]],
    audit: Audit,
) -> None:
    """Enforce approval on server; persistence and audit must be durable adapters."""
    if not proposal.evidence or any(not e.source_id for e in proposal.evidence):
        raise ValueError("recommendation must cite evidence")
    if not await authorize(scope, "review_recommendation"):
        await audit(scope, proposal.proposal_id, "blocked:authorization")
        raise PermissionError("educator cannot review this learner")
    await persist(scope, proposal, decision)
    await audit(scope, proposal.proposal_id, f"teacher:{decision.value}")
