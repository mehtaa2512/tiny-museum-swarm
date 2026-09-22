from __future__ import annotations

import json
import unittest

from tiny_museum.autogen_swarm import agent_system_message, curator_approval_tool, handoffs_for
from tiny_museum.decision import DecisionError, parse_decision


class ProtocolTests(unittest.TestCase):
    def test_structured_decision_parses_handoff(self) -> None:
        decision = parse_decision(json.dumps({
            "public_message": "A grounded observation.",
            "decision_summary": "Found the material basis.",
            "handoff_target": "weaver",
            "handoff_reason": "Connect this fact to cultural practice.",
            "workspace_updates": {"facts": ["fact"]},
            "curator_decision": None,
            "final_exhibition": None,
            "visual_plan": {"center": "Key", "elements": ["Access"], "caption": "A visual map."},
            "tool_calls": [],
        }))
        self.assertEqual(decision.handoff_target, "weaver")
        self.assertEqual(decision.workspace_updates["facts"], ["fact"])
        self.assertEqual(decision.visual_plan["center"], "Key")

    def test_missing_public_summary_is_rejected(self) -> None:
        with self.assertRaises(DecisionError):
            parse_decision('{"public_message":"hello"}')

    def test_each_agent_can_handoff_to_every_other_agent(self) -> None:
        for agent_id in ("scout", "weaver", "storysmith", "curator"):
            targets = {handoff.target for handoff in handoffs_for(agent_id)}
            self.assertEqual(targets, {"scout", "weaver", "storysmith", "curator"} - {agent_id})

    def test_agent_prompt_forbids_hidden_reasoning(self) -> None:
        self.assertIn("Never reveal", agent_system_message("scout"))
        self.assertIn("AutoGen AgentChat Swarm", agent_system_message("scout"))

    def test_curator_has_explicit_approval_tool(self) -> None:
        self.assertEqual(curator_approval_tool().name, "approve_exhibition")
        self.assertIn("approve_exhibition", agent_system_message("curator"))


if __name__ == "__main__":
    unittest.main()
