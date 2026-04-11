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
    assert any(w in result.lower() for w in ("override", "system", "safety"))

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


# ═══════════════════════════════════════════════════════════════════════════════
# S1–S13 FULL CATEGORY COVERAGE
# Every Llama Guard 3 unsafe category must have a registered, non-empty
# explanation in the mapping.  A failure here means users receive no meaningful
# explanation when blocked — treat as a P0 defect.
# ═══════════════════════════════════════════════════════════════════════════════

# Per-category keyword expectations.  At least one keyword must appear in the
# explanation text returned by map_categories_to_explanation([category]).
_S1_S13_KEYWORD_MAP = [
    ("S1",  ["violent", "violence", "harm"]),
    ("S2",  ["chemical", "weapon", "harm"]),
    ("S3",  ["biological", "weapon", "pathogen", "harm"]),
    ("S4",  ["radiological", "nuclear", "weapon", "harm"]),
    ("S5",  ["nuclear", "weapon", "mass", "harm"]),
    ("S6",  ["medical", "advice", "professional", "health"]),
    ("S7",  ["fraud", "financial", "illegal", "harm"]),
    ("S8",  ["child", "minor", "explicit", "harm"]),
    ("S9",  ["weapon", "harm", "mass"]),
    ("S10", ["hate", "abusive", "discriminat"]),
    ("S11", ["harm", "self", "crisis", "support"]),
    ("S12", ["explicit", "sexual", "adult", "harm"]),
    ("S13", ["privacy", "stalk", "track", "harm"]),
]


@pytest.mark.parametrize(
    "category,keywords",
    _S1_S13_KEYWORD_MAP,
    ids=[row[0] for row in _S1_S13_KEYWORD_MAP],
)
def test_s1_s13_all_have_explanations(category, keywords):
    """Every S1–S13 category must produce a non-empty, keyword-matching explanation."""
    result = map_categories_to_explanation([category])
    assert isinstance(result, str) and len(result) > 0, (
        f"[{category}] map_categories_to_explanation returned empty or non-string"
    )
    assert any(kw in result.lower() for kw in keywords), (
        f"[{category}] Explanation {result!r} does not contain any of the "
        f"expected keywords {keywords}"
    )


def test_category_coverage_s1_to_s13():
    """
    Coverage gate: every S1–S13 category must have a non-empty explanation
    registered in the mapping.  Fails immediately if any category is unmapped
    or returns an empty string, preventing silent user-facing messaging gaps.
    """
    mandatory = [f"S{i}" for i in range(1, 14)]
    missing_or_empty = [
        cat for cat in mandatory
        if not map_categories_to_explanation([cat])
    ]
    assert not missing_or_empty, (
        f"The following S1–S13 categories return empty/missing explanations: "
        f"{missing_or_empty}. Add them to map_categories_to_explanation()."
    )
