"""Model output parsing: plans must survive prose, fences and stray fragments."""
import pytest

from app.services.gemini_planner import _extract_json


def test_plain_object():
    assert _extract_json('{"waypoints": []}') == {"waypoints": []}


def test_object_wrapped_in_prose_and_fences():
    text = 'Here is the plan:\n```json\n{"waypoints": [{"x": 1, "y": 2}]}\n```\nDone.'
    assert _extract_json(text) == {"waypoints": [{"x": 1, "y": 2}]}


def test_two_objects_returns_first_instead_of_extra_data_error():
    text = '{"waypoints": [{"x": 1, "y": 2}]} {"note": "second"}'
    assert _extract_json(text) == {"waypoints": [{"x": 1, "y": 2}]}


def test_prefers_object_over_earlier_list_fragment():
    text = 'Candidates [1, 2] considered. {"waypoints": [{"x": 3, "y": 4}]}'
    assert _extract_json(text) == {"waypoints": [{"x": 3, "y": 4}]}


def test_braces_in_prose_before_json_are_skipped():
    text = 'Avoid zone {A} near rack. {"waypoints": []}'
    assert _extract_json(text) == {"waypoints": []}


def test_list_only_is_returned_whole():
    # The agentic planner expects a list of steps here
    assert _extract_json('steps: [{"a": 1}, {"b": 2}]') == [{"a": 1}, {"b": 2}]


def test_truncated_output_raises():
    with pytest.raises(ValueError):
        _extract_json('{"waypoints": [{"x": 1, "y"')
