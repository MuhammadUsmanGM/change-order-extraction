"""Unit tests for configuration loading."""

import os
from unittest.mock import patch

from co_extract.config import Settings, get_settings


def test_default_settings():
    """Verify default setting values when no env vars are passed."""
    with patch.dict(os.environ, {}, clear=True):
        settings = Settings()
        assert settings.anthropic_api_key is None
        assert settings.gemini_api_key is None
        assert settings.claude_model == "claude-3-7-sonnet-20250219"
        assert settings.gemini_model == "gemini-2.5-flash"
        assert settings.max_upload_mb == 10
        assert settings.mock_mode is False


def test_env_override():
    """Verify settings pick up environment variables correctly."""
    custom_env = {
        "ANTHROPIC_API_KEY": "sk-ant-test-key",
        "GEMINI_API_KEY": "AIzaSyTestKey",
        "CLAUDE_MODEL": "claude-3-haiku-20240307",
        "GEMINI_MODEL": "gemini-1.5-flash",
        "MAX_UPLOAD_MB": "25",
        "MOCK_MODE": "true",
    }
    with patch.dict(os.environ, custom_env, clear=True):
        settings = Settings()
        assert settings.anthropic_api_key == "sk-ant-test-key"
        assert settings.gemini_api_key == "AIzaSyTestKey"
        assert settings.claude_model == "claude-3-haiku-20240307"
        assert settings.gemini_model == "gemini-1.5-flash"
        assert settings.max_upload_mb == 25
        assert settings.mock_mode is True


def test_get_settings_cached():
    """Verify get_settings returns a singleton instance."""
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
