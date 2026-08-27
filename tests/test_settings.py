"""Merchant-editable policy, and the review loop that joins OBSERVE to ENFORCE."""

from __future__ import annotations

import shutil

import pytest
import yaml

from commons.ledger.db import Ledger
from commons.rules.engine import RULESET_PATH
from commons.settings import Settings


@pytest.fixture()
def settings(tmp_path):
    """A Settings backed by a COPY of the ruleset, so tests never edit the real one."""
    path = tmp_path / "ruleset.yaml"
    shutil.copy(RULESET_PATH, path)
    from commons.rules.engine import RuleEngine

    return Settings(engine=RuleEngine.load(path), ruleset_path=path)


@pytest.fixture()
def ledger(tmp_path):
    led = Ledger(tmp_path / "review.db")
    led.start_run(mode="OBSERVE")
    yield led
    led.close()


# ---------------------------------------------------------------- configurability


def test_a_merchant_can_lower_the_discount_cap(settings):
    """The headline case: 15% is our demo's number, not everyone's."""
    settings.update_rules([{"id": "discount_cap", "scope": {"cap": 10}}])
    rule = next(r for r in settings.engine.rules if r.id == "discount_cap")
    assert rule.scope["cap"] == 10


def test_changes_survive_a_reload(settings):
    settings.update_rules([{"id": "discount_cap", "scope": {"cap": 12}}])
    written = yaml.safe_load(settings.ruleset_path.read_text(encoding="utf-8"))
    assert next(r for r in written if r["id"] == "discount_cap")["scope"]["cap"] == 12


def test_a_rule_can_be_switched_from_block_to_defer(settings):
    settings.update_rules([{"id": "discount_cap", "on_violation": "DEFER"}])
    assert next(r for r in settings.engine.rules if r.id == "discount_cap").on_violation == "DEFER"


def test_a_rule_can_be_turned_off_without_losing_it(settings):
    settings.update_rules([{"id": "one_agent_per_order", "enabled": False}])
    rule = next(r for r in settings.engine.rules if r.id == "one_agent_per_order")
    assert rule.enabled is False
    # Still present, with its English and thresholds intact.
    assert rule.english and rule.scope


def test_untouched_fields_are_preserved(settings):
    """Changing a cap must not wipe the window or the action classes."""
    before = dict(next(r for r in settings.engine.rules if r.id == "discount_cap").scope)
    settings.update_rules([{"id": "discount_cap", "scope": {"cap": 9}}])
    after = next(r for r in settings.engine.rules if r.id == "discount_cap").scope
    assert after["window"] == before["window"]
    assert after["action_class"] == before["action_class"]


def test_unknown_rule_is_rejected(settings):
    with pytest.raises(ValueError):
        settings.update_rules([{"id": "not_a_rule", "scope": {"cap": 1}}])


def test_bad_verdict_is_rejected(settings):
    with pytest.raises(ValueError):
        settings.update_rules([{"id": "discount_cap", "on_violation": "MAYBE"}])


def test_mode_can_be_switched(settings):
    assert settings.set_mode("ENFORCE") == "ENFORCE"
    with pytest.raises(ValueError):
        settings.set_mode("SOMETIMES")


# ---------------------------------------------------------------- English vs enforced


def test_shipped_rules_say_what_they_enforce(settings):
    """Every rule as shipped must agree with its own sentence."""
    for rule in settings.engine.rules:
        assert Settings.english_disagrees(rule) is None, rule.id


def test_editing_a_threshold_without_the_sentence_is_flagged(settings):
    """The screen must not state one number while the gateway enforces another."""
    settings.update_rules([{"id": "discount_cap", "scope": {"cap": 10}}])
    rule = next(r for r in settings.engine.rules if r.id == "discount_cap")
    mismatch = Settings.english_disagrees(rule)
    assert mismatch and "15" in mismatch


def test_a_shared_number_does_not_excuse_a_changed_one(settings):
    """'more than 15% in any 30-day period' against a cap of 10 still shares the 30.

    An intersection test would pass that and let the sentence keep lying about the
    number that actually matters.
    """
    settings.update_rules([{"id": "discount_cap", "scope": {"cap": 10}}])
    rule = next(r for r in settings.engine.rules if r.id == "discount_cap")
    assert "30" in str(rule.scope["window"])
    assert Settings.english_disagrees(rule) is not None


def test_updating_both_together_clears_the_flag(settings):
    settings.update_rules(
        [
            {
                "id": "discount_cap",
                "scope": {"cap": 10},
                "english": "No customer receives more than 10% total discount in any 30-day period.",
            }
        ]
    )
    rule = next(r for r in settings.engine.rules if r.id == "discount_cap")
    assert Settings.english_disagrees(rule) is None


# ---------------------------------------------------------------- the review loop


def test_a_merchant_verdict_is_recorded(ledger):
    call_id = ledger.record_call(
        agent_id="cart-recovery", upstream="razorpay", tool="create_payment_link",
        action_class="discount_grant", forwarded=1,
    )
    ledger.record_review(call_id, "discount_cap", "incorrect", "retry on same subscription")
    assert ledger.rule_accuracy()["discount_cap"]["incorrect"] == 1


def test_verdicts_are_per_rule_not_per_call(ledger):
    """One call can breach two rules, and a merchant may agree with one and not the
    other — so the verdict has to attach to the pair."""
    call_id = ledger.record_call(
        agent_id="cart-recovery", upstream="razorpay", tool="create_payment_link",
        action_class="discount_grant", forwarded=1,
    )
    ledger.record_review(call_id, "discount_cap", "incorrect")
    ledger.record_review(call_id, "no_promo_during_dispute", "correct")

    accuracy = ledger.rule_accuracy()
    assert accuracy["discount_cap"]["incorrect"] == 1
    assert accuracy["no_promo_during_dispute"]["correct"] == 1


def test_a_verdict_can_be_changed(ledger):
    call_id = ledger.record_call(
        agent_id="rto-shield", upstream="razorpay", tool="update_order", forwarded=1
    )
    ledger.record_review(call_id, "discount_cap", "correct")
    ledger.record_review(call_id, "discount_cap", "incorrect")
    accuracy = ledger.rule_accuracy()["discount_cap"]
    assert accuracy.get("incorrect") == 1 and "correct" not in accuracy


def test_accuracy_identifies_a_rule_that_keeps_being_wrong(ledger):
    """The signal a merchant actually needs before switching on ENFORCE."""
    for _ in range(3):
        call_id = ledger.record_call(
            agent_id="subscription-recovery", upstream="razorpay",
            tool="create_payment_link", action_class="discount_grant", forwarded=1,
        )
        ledger.record_review(call_id, "discount_cap", "incorrect")

    stats = ledger.rule_accuracy()["discount_cap"]
    assert stats["incorrect"] == 3
    assert stats.get("correct", 0) == 0
