import pytest
from models.block_response import map_categories_to_explanation, BlockedResponse

def test_s1_explanation():
    assert "violent" in map_categories_to_explanation(["S1"]).lower()

def test_s9_explanation():
    assert "weapon" in map_categories_to_explanation(["S9"]).lower()

def test_s10_explanation():
    result = map_categories_to_explanation(["S10"])
    assert "hate" in result.lower() or "abusive" in result.lower()

def test_s11_explanation():
    result = map_categories_to_explanation(["S11"])
    assert "harm" in result.lower()

def test_s6_explanation():
    assert "advice" in map_categories_to_explanation(["S6"]).lower()

def test_s15_explanation():
    result = map_categories_to_explanation(["S15"])
    assert any(w in result.lower() for w in ("override", "jailbreak", "system", "safety"))

def test_multiple_categories_returns_single_string():
    result = map_categories_to_explanation(["S1", "S9"])
    assert isinstance(result, str) and len(result) > 0

def test_unknown_category_returns_generic():
    result = map_categories_to_explanation(["S99"])
    assert isinstance(result, str) and len(result) > 0

def test_empty_categories_returns_generic():
    result = map_categories_to_explanation([])
    assert isinstance(result, str) and len(result) > 0

def test_explanation_never_contains_raw_model_text():
    """Explanation must come from mapping only — never raw Llama Guard output."""
    result = map_categories_to_explanation(["S1", "S9"])
    # Raw Llama Guard format is "unsafe\nS1,S9" — must never appear
    assert "unsafe" not in result.lower()
    assert "\n" not in result
    assert "llama" not in result.lower()

def test_blocked_response_schema():
    r = BlockedResponse(
        error="blocked_by_policy",
        reason="llama_guard_unsafe_category",
        categories=["S1"],
        explanation="This involves violence.",
        session_id="s1",
        correlation_id="c1",
    )
    assert r.error == "blocked_by_policy"
    assert r.categories == ["S1"]
    d = r.model_dump()
    assert all(k in d for k in ("error", "reason", "categories", "explanation", "session_id", "correlation_id"))
