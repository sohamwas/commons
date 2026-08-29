"""A vendor is any MCP server, not a name baked into config.py.

The list used to be two hardcoded entries, which quietly made Commons a
Razorpay-and-messaging tool rather than an arbitration layer for whatever a merchant
actually runs.

Secrets stay in .env: a header written as "env:NAME" is resolved at connect time, so a
token never lands in a YAML file that is easier to leak than an environment.
"""

from __future__ import annotations

import pytest

from commons.proxy.vendors import InvalidVendor, VendorDef, VendorRegistry, parse_vendor


@pytest.fixture
def registry(tmp_path, monkeypatch):
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    return VendorRegistry(tmp_path / "vendors.yaml")


# ---------------------------------------------------------------- validation


def test_any_mcp_url_is_accepted():
    v = parse_vendor("my-crm", {"url": "https://mcp.example.com/mcp"})
    assert v.name == "my-crm"
    assert v.to_upstream().url == "https://mcp.example.com/mcp"


@pytest.mark.parametrize("name", ["", "My CRM", "crm/two", "-lead", "UPPER"])
def test_names_that_cannot_be_a_url_segment_are_refused(name):
    with pytest.raises(InvalidVendor):
        parse_vendor(name, {"url": "https://mcp.example.com/mcp"})


@pytest.mark.parametrize("url", ["", "not-a-url", "ftp://x/mcp", "mcp.example.com"])
def test_a_non_http_url_is_refused(url):
    with pytest.raises(InvalidVendor, match="http"):
        parse_vendor("crm", {"url": url})


# ---------------------------------------------------------------- secrets


def test_a_header_can_be_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cret")
    v = parse_vendor(
        "crm", {"url": "https://x/mcp", "headers": {"Authorization": "env:MY_TOKEN"}}
    )
    assert v.to_upstream().headers["Authorization"] == "s3cret"


def test_a_missing_environment_secret_is_refused_with_the_variable_name(monkeypatch):
    monkeypatch.delenv("MY_TOKEN", raising=False)
    v = parse_vendor(
        "crm", {"url": "https://x/mcp", "headers": {"Authorization": "env:MY_TOKEN"}}
    )
    with pytest.raises(InvalidVendor, match="MY_TOKEN"):
        v.to_upstream()


def test_the_secret_itself_is_never_written_to_the_file(registry, monkeypatch):
    monkeypatch.setenv("MY_TOKEN", "s3cret")
    registry.add(
        parse_vendor("crm", {"url": "https://x/mcp", "headers": {"Authorization": "env:MY_TOKEN"}})
    )
    text = registry.path.read_text(encoding="utf-8")
    assert "env:MY_TOKEN" in text
    assert "s3cret" not in text


# ---------------------------------------------------------------- persistence


def test_a_vendor_survives_a_restart(registry):
    registry.add(parse_vendor("crm", {"url": "https://x/mcp"}))
    assert len(VendorRegistry(registry.path)) == 1


def test_removing_persists(registry):
    registry.add(parse_vendor("crm", {"url": "https://x/mcp"}))
    assert registry.remove("crm") is True
    assert registry.remove("crm") is False
    assert len(VendorRegistry(registry.path)) == 0


def test_one_bad_entry_does_not_hide_the_good_ones(tmp_path):
    path = tmp_path / "vendors.yaml"
    path.write_text(
        "vendors:\n"
        "  good:\n"
        "    url: https://good.example.com/mcp\n"
        "  bad:\n"
        "    url: not-a-url\n",
        encoding="utf-8",
    )
    assert [v.name for v in VendorRegistry(path)] == ["good"]


def test_razorpay_is_seeded_only_when_its_keys_exist(tmp_path, monkeypatch):
    """An entry that cannot authenticate is worse than no entry."""
    monkeypatch.delenv("RAZORPAY_KEY_ID", raising=False)
    assert len(VendorRegistry(tmp_path / "a.yaml")) == 0

    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_x")
    seeded = VendorRegistry(tmp_path / "b.yaml")
    assert [v.name for v in seeded] == ["razorpay"]


def test_upstream_configs_skips_vendors_it_cannot_build(registry, monkeypatch):
    """A vendor missing its secret must not stop the others from connecting."""
    monkeypatch.delenv("MISSING", raising=False)
    registry.add(parse_vendor("ok", {"url": "https://ok.example.com/mcp"}))
    registry.add(
        parse_vendor("broken", {"url": "https://x/mcp", "headers": {"A": "env:MISSING"}})
    )
    assert list(registry.upstream_configs()) == ["ok"]


def test_round_trips_through_yaml(registry):
    registry.add(VendorDef(name="crm", url="https://x/mcp", headers={"A": "b"}))
    back = VendorRegistry(registry.path).get("crm")
    assert back.url == "https://x/mcp"
    assert back.headers == {"A": "b"}


def test_a_secret_composes_with_a_scheme(monkeypatch):
    """Bearer env:TOKEN is the shape almost every hosted MCP server wants.

    Resolving only values that STARTED with env: made this impossible: the bare form sent
    a token with no scheme, and the composed form was sent literally. Both came back
    Unauthorized, which is a confusing way to discover the placeholder does not compose.
    """
    monkeypatch.setenv("RESEND_API_KEY", "re_abc123")
    v = parse_vendor(
        "resend",
        {"url": "https://x/mcp", "headers": {"Authorization": "Bearer env:RESEND_API_KEY"}},
    )
    assert v.to_upstream().headers["Authorization"] == "Bearer re_abc123"


def test_several_secrets_in_one_value(monkeypatch):
    monkeypatch.setenv("A_ID", "id1")
    monkeypatch.setenv("A_SECRET", "s1")
    v = parse_vendor("x", {"url": "https://x/mcp", "headers": {"X": "env:A_ID:env:A_SECRET"}})
    assert v.to_upstream().headers["X"] == "id1:s1"


def test_a_value_with_no_placeholder_is_left_alone():
    v = parse_vendor("x", {"url": "https://x/mcp", "headers": {"X-Api-Version": "2024-01"}})
    assert v.to_upstream().headers["X-Api-Version"] == "2024-01"
