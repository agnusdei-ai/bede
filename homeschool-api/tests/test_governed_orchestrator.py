import asyncio
import unittest

from services.governed_orchestrator import (
    GovernedOrchestrator, Scope, Result, TaskStatus, Evidence,
    Recommendation, Decision, review_recommendation,
)


class OrchestratorTests(unittest.TestCase):
    def test_dependencies_and_authorization(self):
        async def scenario():
            events = []
            scope = Scope("campus-a", "learner-a", "teacher-a")
            async def auth(s, task):
                return s.campus_id == "campus-a" and task != "export"
            async def audit(s, task, event):
                events.append((task, event))
            async def evidence(s, deps):
                return ["assessment-1"]
            async def recommendation(s, deps):
                return Recommendation("Review phonics", (Evidence("assessment-1", "Check-in"),))
            async def export(s, deps):
                raise AssertionError("must not run")
            o = GovernedOrchestrator(auth, audit, max_parallel=2)
            result = await o.run(scope, {
                "evidence": ((), evidence),
                "recommend": (("evidence",), recommendation),
                "export": (("recommend",), export),
            })
            self.assertEqual(result["evidence"].status, TaskStatus.SUCCEEDED)
            self.assertEqual(result["recommend"].status, TaskStatus.SUCCEEDED)
            self.assertEqual(result["export"].status, TaskStatus.BLOCKED)
            self.assertIn(("export", "blocked:authorization"), events)
        asyncio.run(scenario())

    def test_failure_blocks_dependents(self):
        async def scenario():
            async def auth(s, task): return True
            async def audit(s, task, event): pass
            async def broken(s, deps): raise RuntimeError("sensitive detail")
            async def downstream(s, deps): raise AssertionError("should not execute")
            result = await GovernedOrchestrator(auth, audit).run(
                Scope("c", "l", "t"),
                {"broken": ((), broken), "next": (("broken",), downstream)},
            )
            self.assertEqual(result["broken"].error, "agent execution failed")
            self.assertEqual(result["next"].status, TaskStatus.BLOCKED)
        asyncio.run(scenario())

    def test_teacher_review_enforced(self):
        async def scenario():
            saved = []
            events = []
            async def auth(scope, task): return scope.campus_id == "campus-a"
            async def audit(scope, task, event): events.append(event)
            async def persist(scope, proposal, decision): saved.append(decision)
            rec = Recommendation("Practice reading", (Evidence("source-1", "Observation"),))
            await review_recommendation(Scope("campus-a", "learner", "teacher"), rec,
                                        Decision.EDIT, authorize=auth, persist=persist, audit=audit)
            self.assertEqual(saved, [Decision.EDIT])
            with self.assertRaises(PermissionError):
                await review_recommendation(Scope("campus-b", "learner", "teacher"), rec,
                                            Decision.APPROVE, authorize=auth, persist=persist, audit=audit)
            self.assertEqual(saved, [Decision.EDIT])
        asyncio.run(scenario())

    def test_disconnected_cycle_rejected_before_any_agent_or_audit(self):
        async def scenario():
            side_effects = []
            scope = Scope("campus-a", "learner-a", "teacher-a")

            async def authorize(s, task):
                side_effects.append(("authorize", task))
                return True

            async def audit(s, task, event):
                side_effects.append(("audit", task, event))

            async def write_capable_agent(s, deps):
                side_effects.append(("agent", s.learner_id))
                return True

            # An unrelated ready task must NOT execute before a later
            # disconnected cycle is discovered.
            tasks = {
                "independent": ((), write_capable_agent),
                "loop-a": (("loop-b",), write_capable_agent),
                "loop-b": (("loop-a",), write_capable_agent),
            }
            with self.assertRaisesRegex(ValueError, "cyclic"):
                await GovernedOrchestrator(authorize, audit).run(scope, tasks)
            self.assertEqual(side_effects, [])
        asyncio.run(scenario())

    def test_malformed_teacher_decision_never_persists(self):
        async def scenario():
            writes = []
            audits = []
            async def auth(scope, action):
                return True
            async def persist(*args):
                writes.append(args)
            async def audit(scope, subject, event):
                audits.append(event)
            scope = Scope("campus-a", "learner-a", "teacher-a")
            proposal = Recommendation("Review reading", (Evidence("e1", "Observation"),))
            for invalid in ("approve", None, "unknown"):
                with self.assertRaises(ValueError):
                    await review_recommendation(
                        scope, proposal, invalid, authorize=auth,
                        persist=persist, audit=audit,
                    )
            self.assertEqual(writes, [])
            self.assertEqual(audits, [])
        asyncio.run(scenario())

    def test_invalid_dag_and_missing_evidence(self):
        async def scenario():
            async def auth(s, t): return True
            async def audit(s, t, e): pass
            async def agent(s, deps): return True
            o = GovernedOrchestrator(auth, audit)
            with self.assertRaises(ValueError):
                await o.run(Scope("c", "l", "t"), {"a": (("b",), agent), "b": (("a",), agent)})
            async def persist(*args): raise AssertionError("should not persist")
            with self.assertRaises(ValueError):
                await review_recommendation(Scope("c", "l", "t"), Recommendation("x", ()),
                                            Decision.APPROVE, authorize=auth, persist=persist, audit=audit)
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
