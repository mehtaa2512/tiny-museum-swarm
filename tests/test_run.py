from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tiny_museum.config import load_config
from tiny_museum.models import AgentDecision, ProviderConfig
from tiny_museum.run import SwarmRun


class DemoRunTests(unittest.TestCase):
    def test_curator_approval_generates_image_before_completion(self) -> None:
        class FakeImageGenerator:
            def generate(self, prompt: str, destination: Path) -> None:
                self.prompt = prompt
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"\x89PNG\r\n\x1a\n")

        config = load_config()
        generator = FakeImageGenerator()
        with tempfile.TemporaryDirectory() as directory:
            run = SwarmRun("a key", config, Path(directory), image_generator=generator)
            run._complete_from_curator(
                AgentDecision(
                    public_message="Approved.",
                    decision_summary="Ready.",
                    curator_decision="approve",
                    final_exhibition="# A Key",
                    visual_plan={"center": "key", "elements": ["lock"], "caption": "A key museum."},
                )
            )
            event_types = [event.type for event in run.events]
            self.assertLess(event_types.index("curator_approval"), event_types.index("image_generation_started"))
            self.assertLess(event_types.index("image_generated"), event_types.index("run_completed"))
            self.assertTrue(run.image_path.is_file())
            self.assertIn("miniature museum", generator.prompt)

    def test_demo_run_rejects_revises_and_only_curator_completes(self) -> None:
        config = load_config()
        config.image_generation.enabled = False
        config.providers = {"demo": ProviderConfig(kind="demo", base_url="demo://local")}
        for agent in config.agents.values():
            agent.provider = "demo"
            agent.model = "museum-demo"
        with tempfile.TemporaryDirectory() as directory:
            run = SwarmRun("a key", config, Path(directory))
            run._run()
            event_types = [event.type for event in run.events]
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.termination_reason, "curator_approved")
            self.assertIn("curator_rejection", event_types)
            self.assertIn("curator_approval", event_types)
            self.assertIn("tool_call", event_types)
            self.assertIn("tool_result", event_types)
            self.assertEqual(run.events[-1].agent, "curator")
            self.assertEqual(run.ledger.model_calls, 6)
            self.assertEqual(run.ledger.handoffs, 5)
            self.assertTrue(run.workspace.final_exhibition)
            self.assertTrue(run.workspace.final_visual_plan)
            self.assertTrue((Path(directory) / f"{run.id}.json").exists())

    def test_pre_requested_cancellation_makes_no_model_call(self) -> None:
        config = load_config()
        config.image_generation.enabled = False
        config.providers = {"demo": ProviderConfig(kind="demo", base_url="demo://local")}
        for agent in config.agents.values():
            agent.provider = "demo"
        with tempfile.TemporaryDirectory() as directory:
            run = SwarmRun("an umbrella", config, Path(directory))
            run.cancel_requested.set()
            run._run()
            self.assertEqual(run.status, "cancelled")
            self.assertEqual(run.ledger.model_calls, 0)
            self.assertEqual(run.termination_reason, "manual_cancellation")

    def test_handoff_reroutes_when_preferred_agent_budget_is_spent(self) -> None:
        config = load_config()
        config.image_generation.enabled = False
        config.providers = {"demo": ProviderConfig(kind="demo", base_url="demo://local")}
        for agent in config.agents.values():
            agent.provider = "demo"
        with tempfile.TemporaryDirectory() as directory:
            run = SwarmRun("a key", config, Path(directory))
            run.ledger.per_agent_tokens["scout"] = 19_500
            run.ledger.total_tokens = 19_500
            target, reason = run._resolve_target("curator", "scout", "Verify one more claim.")
            self.assertEqual(target, "storysmith")
            self.assertIn("lacks enough personal budget", reason)

    def test_repeated_curator_rejections_require_human_review(self) -> None:
        config = load_config()
        with tempfile.TemporaryDirectory() as directory:
            run = SwarmRun("rain", config, Path(directory))
            self.assertIsNone(run._record_curator_rejection(True))
            self.assertIsNone(run._record_curator_rejection(True))
            reason = run._record_curator_rejection(True)
            self.assertIn("needs human review", reason)


if __name__ == "__main__":
    unittest.main()
