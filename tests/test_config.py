from __future__ import annotations

import copy
import unittest

from tiny_museum.config import apply_runtime_agent_config, load_config, public_config, validate_config


class ConfigTests(unittest.TestCase):
    def test_public_config_does_not_expose_key_variable_names(self) -> None:
        public = public_config(load_config())
        for provider in public["providers"].values():
            self.assertNotIn("api_key_env", provider)

    def test_runtime_update_is_agent_specific(self) -> None:
        config = load_config()
        original_weaver = config.agents["weaver"].model
        apply_runtime_agent_config(config, {"scout": {"provider": "ollama", "model": "gpt-oss:20b"}})
        self.assertEqual(config.agents["scout"].model, "gpt-oss:20b")
        self.assertEqual(config.agents["weaver"].model, original_weaver)

    def test_budgets_must_sum_to_global_limit(self) -> None:
        config = copy.deepcopy(load_config())
        config.agents["scout"].token_budget -= 1
        with self.assertRaises(ValueError):
            validate_config(config)

    def test_z_image_turbo_fp8_is_enabled(self) -> None:
        config = load_config()
        self.assertTrue(config.image_generation.enabled)
        self.assertEqual(config.image_generation.provider, "ollama_image")
        self.assertEqual(config.image_generation.model, "x/z-image-turbo:fp8")


if __name__ == "__main__":
    unittest.main()
