"""Unit tests for scope_context — no Neo4j required."""

from __future__ import annotations

import pytest

from scope_context import (
    DEFAULT_SCOPE,
    get_scope_filter,
    reset_scope_filter,
    set_scope_filter,
    validate_scope,
)


@pytest.mark.unit
class TestValidateScope:
    def test_shared(self) -> None:
        assert validate_scope("shared") == "shared"

    def test_valid_tenant(self) -> None:
        assert validate_scope("tenant:clinic-a") == "tenant:clinic-a"
        assert validate_scope("tenant:abc") == "tenant:abc"
        assert validate_scope("tenant:clinic-123-test") == "tenant:clinic-123-test"

    def test_rejects_uppercase_tenant(self) -> None:
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            validate_scope("tenant:Clinic-A")

    def test_rejects_underscore_tenant(self) -> None:
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            validate_scope("tenant:clinic_a")

    def test_rejects_leading_hyphen(self) -> None:
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            validate_scope("tenant:-clinic")

    def test_rejects_empty_tenant(self) -> None:
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            validate_scope("tenant:")

    def test_rejects_too_short(self) -> None:
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            validate_scope("tenant:ab")

    def test_rejects_too_long(self) -> None:
        with pytest.raises(ValueError, match="Invalid tenant slug"):
            validate_scope("tenant:" + "a" * 65)

    def test_rejects_injection_attempt(self) -> None:
        with pytest.raises(ValueError):
            validate_scope("tenant:'; DROP TABLE")

    def test_rejects_unknown_prefix(self) -> None:
        with pytest.raises(ValueError, match="Invalid scope"):
            validate_scope("public:x")


@pytest.mark.unit
class TestScopeFilter:
    def test_default_is_shared(self) -> None:
        # Default behaviour when nothing is set.
        assert get_scope_filter() == list(DEFAULT_SCOPE)

    def test_set_and_reset(self) -> None:
        token = set_scope_filter(["shared", "tenant:clinic-a"])
        try:
            assert get_scope_filter() == ["shared", "tenant:clinic-a"]
        finally:
            reset_scope_filter(token)
        assert get_scope_filter() == list(DEFAULT_SCOPE)

    def test_nested_set_reset(self) -> None:
        outer = set_scope_filter(["shared", "tenant:clinic-a"])
        try:
            inner = set_scope_filter(["shared", "tenant:clinic-b"])
            try:
                assert get_scope_filter() == ["shared", "tenant:clinic-b"]
            finally:
                reset_scope_filter(inner)
            assert get_scope_filter() == ["shared", "tenant:clinic-a"]
        finally:
            reset_scope_filter(outer)

    def test_rejects_empty_list(self) -> None:
        with pytest.raises(ValueError, match="cannot be empty"):
            set_scope_filter([])

    def test_rejects_invalid_scope_in_list(self) -> None:
        with pytest.raises(ValueError):
            set_scope_filter(["shared", "tenant:BAD-UPPER"])
