"""Registering an agent is a merchant action, not a code change.

The registry used to be a dict in registry.py, so onboarding an agent meant editing
Python and restarting a gateway that other agents were connected to. It is a file now,
written by the admin API and safe to edit by hand.

Validation refuses rather than half-registers, because a half-registered agent is an
endpoint that exists and does not work.
"""

from __future__ import annotations

import pytest

from commons.proxy.registry import AgentRegistry, AgentSpec, InvalidAgent, parse_agent

VALID = {
    "display_name": "Cart Recovery",
    "tools": {"razorpay": ["create_payment_link"], "messaging": ["send_whatsapp"]},
}


@pytest.fixture
def registry(tmp_path):
    return AgentRegistry(tmp_path / "agents.yaml")


# ---------------------------------------------------------------- validation


def test_a_valid_agent_parses():
    spec = parse_agent("cart-recovery", VALID)
    assert spec.id == "cart-recovery"
    assert spec.allowed("razorpay") == ("create_payment_link",)
    assert spec.allowed("messaging") == ("send_whatsapp",)
    assert spec.allowed("stripe") == ()


@pytest.mark.parametrize(
    "agent_id",
    ["", "Cart Recovery", "cart/recovery", "-leading", "UPPER", "a" * 64, "with space"],
)
def test_ids_that_cannot_be_a_url_segment_are_refused(agent_id):
    with pytest.raises(InvalidAgent):
        parse_agent(agent_id, VALID)


def test_an_agent_with_no_tools_is_refused():
    with pytest.raises(InvalidAgent, match="nothing to call"):
        parse_agent("empty", {"tools": {}})


def test_an_unconfigured_vendor_is_refused():
    with pytest.raises(InvalidAgent, match="not configured"):
        parse_agent("x", {"tools": {"stripe": ["charge"]}}, known_upstreams={"razorpay"})


def test_the_error_names_the_vendors_that_do_exist():
    with pytest.raises(InvalidAgent, match="razorpay"):
        parse_agent("x", {"tools": {"stripe": ["charge"]}}, known_upstreams={"razorpay"})


def test_a_single_tool_may_be_written_as_a_string():
    """Hand-edited YAML will do this, and refusing it would be pedantry."""
    spec = parse_agent("x", {"tools": {"razorpay": "fetch_order"}})
    assert spec.allowed("razorpay") == ("fetch_order",)


# ---------------------------------------------------------------- persistence


def test_an_agent_survives_a_restart(registry):
    registry.add(parse_agent("cart-recovery", VALID))
    assert len(AgentRegistry(registry.path)) == 1


def test_the_written_file_is_readable_and_editable(registry):
    registry.add(parse_agent("cart-recovery", VALID))
    text = registry.path.read_text(encoding="utf-8")
    assert "cart-recovery" in text
    assert "create_payment_link" in text
    assert text.lstrip().startswith("#"), "the file a merchant may edit should say what it is"


def test_re_adding_replaces_rather_than_duplicates(registry):
    registry.add(parse_agent("cart-recovery", VALID))
    registry.add(parse_agent("cart-recovery", {"tools": {"razorpay": ["fetch_order"]}}))
    assert len(registry) == 1
    assert registry.get("cart-recovery").allowed("razorpay") == ("fetch_order",)


def test_removing_persists(registry):
    registry.add(parse_agent("cart-recovery", VALID))
    assert registry.remove("cart-recovery") is True
    assert registry.remove("cart-recovery") is False
    assert len(AgentRegistry(registry.path)) == 0


def test_a_missing_file_is_an_empty_registry(tmp_path):
    assert len(AgentRegistry(tmp_path / "nothing-here.yaml")) == 0


def test_one_bad_entry_does_not_hide_the_good_ones(tmp_path):
    """A hand-edited file with a mistake in it must not take the gateway down."""
    path = tmp_path / "agents.yaml"
    path.write_text(
        "agents:\n"
        "  good:\n"
        "    tools:\n"
        "      razorpay: [fetch_order]\n"
        "  bad:\n"
        "    tools: {}\n",
        encoding="utf-8",
    )
    registry = AgentRegistry(path)
    assert [a.id for a in registry] == ["good"]


def test_display_name_defaults_to_the_id():
    assert parse_agent("cart-recovery", {"tools": {"razorpay": ["fetch_order"]}}).display_name == (
        "cart-recovery"
    )


def test_round_trips_through_yaml(registry):
    spec = AgentSpec(
        id="a", display_name="A", tools={"razorpay": ("fetch_order", "update_order")}
    )
    registry.add(spec)
    assert AgentRegistry(registry.path).get("a") == spec
