"""Unit tests for triage._extract_json_obj — sole defense against
free-tier Nemotron padded/wrapped JSON output. Per code review T1."""
import pytest

from agents.triage import _extract_json_obj  # type: ignore[import-not-found]

pytestmark = [pytest.mark.unit]


def test_strips_surrounding_text():
    padded = 'Sure! Here is the JSON: {"intervention":"ginger","outcome":"nausea"}   \n\n'
    assert _extract_json_obj(padded) == '{"intervention":"ginger","outcome":"nausea"}'


def test_returns_input_when_no_brace():
    assert _extract_json_obj("No JSON here.") == "No JSON here."


def test_handles_nested_objects():
    s = '{"a":{"b":1},"c":2}'
    assert _extract_json_obj(s) == s


def test_handles_arrays_with_objects():
    s = '{"list":[{"k":1},{"k":2}],"n":3}'
    assert _extract_json_obj(s) == s


def test_handles_escaped_quotes_in_strings():
    """The hand-rolled walker miscounted on \\" — replaced with
    json.JSONDecoder().raw_decode which handles all escape sequences."""
    s = '{"text":"She said \\"hi\\"","other":1}'
    assert _extract_json_obj(s) == s


def test_handles_escaped_backslashes():
    """Escaped backslash before quote was the failure case for the
    hand-rolled walker (\\\\\\" → in_str toggle at wrong position)."""
    s = '{"path":"C:\\\\foo\\\\bar","ok":true}'
    assert _extract_json_obj(s) == s


def test_strips_markdown_code_fence():
    """Free-tier Nemotron wraps JSON in ```json ... ``` fences."""
    padded = '```json\n{"intervention":"ginger"}\n```\n'
    out = _extract_json_obj(padded)
    assert out == '{"intervention":"ginger"}'


def test_handles_multiple_top_level_objects_picks_first():
    """If the LLM hallucinates trailing JSON after the first object,
    the extractor returns just the first balanced object."""
    s = '{"a":1}\n{"b":2}'
    assert _extract_json_obj(s) == '{"a":1}'


def test_returns_partial_slice_on_unbalanced_input():
    """Truncated/unbalanced input falls through to the start: slice;
    Pydantic will then raise a ValidationError with the partial."""
    s = '{"a":1,"b":'  # truncated — no closing brace
    out = _extract_json_obj(s)
    assert out.startswith('{"a":1,"b":')
