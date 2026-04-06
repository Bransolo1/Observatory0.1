"""Tests for LLM analytical lens prompts."""

from observatory.core.llm.service import LENS_PROMPTS


def test_all_three_lenses_defined():
    assert "academic" in LENS_PROMPTS
    assert "business" in LENS_PROMPTS
    assert "ux" in LENS_PROMPTS


def test_lenses_are_non_empty():
    for lens, prompt in LENS_PROMPTS.items():
        assert len(prompt) > 50, f"Lens '{lens}' prompt too short"
