from __future__ import annotations

import unittest

from vdagent_chart.settings import load_settings


class SettingsTests(unittest.TestCase):
    def test_defaults_to_gpt_4o_mini_when_model_is_omitted(self) -> None:
        settings = load_settings(
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_BASE_URL": "https://api.openai.com/v1",
            }
        )

        self.assertEqual(settings.llm_model, "gpt-4o-mini")
        self.assertEqual(settings.llm_timeout_s, 120.0)

    def test_rejects_missing_openai_api_key(self) -> None:
        with self.assertRaisesRegex(Exception, "OPENAI_API_KEY"):
            load_settings({"OPENAI_BASE_URL": "https://api.openai.com/v1"})
