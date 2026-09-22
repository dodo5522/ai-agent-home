"""Tests for the private JSON-to-domain decoding boundary."""

import pytest

from herdr_runtime import HerdrError
from herdr_runtime._decoding import (
    JsonObject,
    optional_string,
    required_object,
    required_string,
)


def test_required_object_returns_validated_nested_object() -> None:
    assert required_object({"workspace": {"workspace_id": "w1"}}, "workspace") == {
        "workspace_id": "w1"
    }


@pytest.mark.parametrize("payload", [{}, {"workspace": []}, {"workspace": "w1"}])
def test_required_object_rejects_missing_or_non_object_value(payload: JsonObject) -> None:
    with pytest.raises(HerdrError, match="workspace object"):
        required_object(payload, "workspace")


@pytest.mark.parametrize("payload", [{}, {"name": ""}, {"name": 1}])
def test_required_string_rejects_missing_empty_or_non_string_value(
    payload: JsonObject,
) -> None:
    with pytest.raises(HerdrError, match="name"):
        required_string(payload, "name")


def test_optional_string_distinguishes_absence_from_invalid_value() -> None:
    assert optional_string({}, "cwd") is None
    assert optional_string({"cwd": "/work/repo"}, "cwd") == "/work/repo"
    with pytest.raises(HerdrError, match="cwd"):
        optional_string({"cwd": 1}, "cwd")
