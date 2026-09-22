from __future__ import annotations

import unittest

from tiny_museum.budget import BudgetExceeded, BudgetLedger
from tiny_museum.config import load_config
from tiny_museum.models import Usage


class BudgetLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = load_config()
        self.ledger = BudgetLedger(self.config)

    def test_pair_limit_is_direction_independent(self) -> None:
        self.ledger.record_handoff("scout", "curator")
        self.ledger.record_handoff("curator", "scout")
        allowed, reason = self.ledger.can_handoff("scout", "curator")
        self.assertFalse(allowed)
        self.assertIn("Repeated", reason)

    def test_specialist_cannot_start_after_reserve_threshold(self) -> None:
        self.ledger.total_tokens = self.config.limits.curator_reserve_starts_at
        with self.assertRaises(BudgetExceeded):
            self.ledger.output_allowance("scout", 100)
        self.assertGreater(self.ledger.output_allowance("curator", 100), 0)

    def test_usage_cannot_cross_agent_budget(self) -> None:
        budget = self.config.agents["storysmith"].token_budget
        with self.assertRaises(BudgetExceeded):
            self.ledger.record_call("storysmith", Usage(budget, 1), 0)

    def test_warning_fires_only_once(self) -> None:
        self.ledger.total_tokens = int(self.config.limits.total_tokens * self.config.limits.warn_at_fraction)
        self.assertTrue(self.ledger.warning_due())
        self.assertFalse(self.ledger.warning_due())


if __name__ == "__main__":
    unittest.main()
