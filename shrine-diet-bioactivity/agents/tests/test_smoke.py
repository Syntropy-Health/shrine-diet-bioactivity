"""Smoke test — confirms AG2 installs cleanly and basic ConversableAgent works."""
import pytest

pytestmark = [pytest.mark.unit]


def test_ag2_imports():
    import autogen  # ag2 publishes under both `ag2` and `autogen` aliases
    assert hasattr(autogen, "ConversableAgent")
    assert hasattr(autogen, "GroupChat")
    assert hasattr(autogen, "GroupChatManager")


def test_pydantic_v2_available():
    from pydantic import BaseModel, Field
    class Probe(BaseModel):
        x: int = Field(ge=0)
    assert Probe(x=1).x == 1
    with pytest.raises(Exception):
        Probe(x=-1)
