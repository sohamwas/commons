# Commons: 5-minute pitch script

Target 5:00. Spoken narration is roughly 620 words; the rest of the time is demo.
Lines in **bold** are spoken. Lines in `[brackets]` are screen directions.

---

## Before you record

```bash
python scripts/start.py --mode ENFORCE
```

Check the header reads **ENFORCE** and the run is `run_533b126090f0`. If it says OBSERVE,
the blocks will not happen and the demo does not land. Have two tabs open: the dashboard
on `localhost:3300` and a terminal.

The two customers you need are **Ishaan Gupta** and **Fatima Sheikh**. Click both once
before recording so the data is warm.

---

## 0:00 to 0:45 — The problem

`[Slide or the dashboard customer grid, not yet scrolled]`

**A merchant runs four AI agents. Cart Recovery chases abandoned baskets. Subscription
Recovery rescues failed mandates. RTO Shield blocks cash-on-delivery for customers who
return too much. Dispute Responder handles chargebacks.**

**Each one is well built. Each has its own limits and stays inside them. Each one is
individually correct.**

**And then this happens. RTO Shield decides a customer is a return risk and locks their
order to prepaid only. An hour later, Cart Recovery offers that same customer ten percent
off to buy.**

**Nobody exceeded a limit. There is no misbehaving agent to find. The merchant is arguing
with itself, and no agent can see it, because no agent can see the other three.**

**Every permission system ever built asks: may this actor do this? That question cannot
catch this, because the answer is yes, every time.**

---

## 0:45 to 1:20 — What Commons is

`[Architecture diagram from the README]`

**Commons is an MCP gateway that sits between your agents and the vendors they call. It
asks a different question. Not "may this agent do this", but "has too much already
happened to this customer".**

**It sits in the path because that is the only place this is knowable. It sees every
agent's calls to every vendor, so it can hold the one piece of state no individual agent
has: the running total for one human being, across all of them.**

`[Show the one-line diff]`

**Integration is one line. You point an agent's MCP config at Commons instead of at the
vendor. Nothing inside the agent changes, which means this works on agents you did not
write and cannot modify.**

---

## 1:20 to 3:40 — Demo

### Example 1: the contradiction (about 70 seconds)

`[Dashboard, click Ishaan Gupta]`

**This is one real customer. Four lanes, one per agent. Everything you are seeing came
from four agents running against live Razorpay and Resend servers.**

`[Point at the timeline, then scroll to Calls]`

**RTO Shield reads his order, then restricts it to prepaid only. Both allowed, both
sensible, because he genuinely is a return risk.**

**Then Cart Recovery, working its own list, tries to give him ten percent off.**

`[Click the red BLOCK row so the panel expands]`

**Blocked. And read the reason, because this is the whole argument:**

> `restriction_beats_incentive: discount_grant contradicts fulfilment_restriction set by
> rto-shield within 7d`

**Two rules fired at once and the stricter one won. The gateway also told Cart Recovery
that RTO Shield holds a lease on that order.**

**Neither agent did anything wrong. Neither exceeded anything. There is no per-agent rule
you could write that catches this, because it is not about either agent. It is about the
customer they are both touching.**

**And this is not a log entry that someone reviews on Monday. Cart Recovery received a
real MCP tool error, in-band, and had to handle it.**

### Example 2: it is a budget, not a ban (about 60 seconds)

`[Click Fatima Sheikh]`

**Second case. Cart Recovery offers this customer ten percent to rescue her basket.
Allowed. Then Subscription Recovery, working her failed mandate, offers eight percent to
keep her.**

`[Point at the blocked row]`

> `discount_cap: 10 + 8 = 18% in 30d, cap 15`

**Ten plus eight is eighteen, against a merchant cap of fifteen. Each agent was well
inside its own ceiling. The customer was not.**

**Now watch what happens next, because this is the part that matters for a real merchant.**

`[Point at the allowed 4% row]`

**Subscription Recovery retried at four percent, and Commons allowed it. She is at
fourteen. It is a budget being spent, not a door being slammed. The agent can still do its
job, just not at the merchant's expense.**

`[Optional, if time allows: click the Rules tab]`

**And these limits are yours. Plain English on the left, the invariant actually enforced
on the right, so you can check the two still agree. Change a threshold and it applies on
the next call. Your agents stay connected.**

---

## 3:40 to 4:25 — Why this holds up

**Two things make this more than a demo.**

**First, Commons reads vendor schemas, never vendor source. A manifest maps each published
tool to what it does and to whom. That is what lets it govern a third-party agent calling
a third-party vendor, which is the actual shape of an agent marketplace.**

**Second, classification is governed by default. A message is promotional unless a
merchant-approved tag says otherwise. An agent cannot exempt itself from a frequency cap by
inventing a label, because only the merchant's list counts. We tested that: the same
marketing email tagged "definitely transactional" is still blocked.**

**And it ships in observe mode. Nothing is blocked, everything is recorded. You watch for a
few days, fix the rules that misfire, and only then enforce. Same engine in both modes,
which means what you watched is exactly what will run.**

---

## 4:25 to 5:00 — Close

**One command from a clean clone brings up the gateway, the dashboard and a second vendor.
Python and Node, nothing else.**

**It runs entirely on your machine. Commons sees payment amounts, customer identifiers and
refund decisions, so it is never hosted for you. The dashboard is something you clone, not
something you log into.**

**What I would still fix: there is no Python lockfile yet, and the discount cap can only be
demonstrated through order metadata because the Razorpay test account is out of payment
link quota. Both are written down in the README rather than hidden.**

**Four agents. One customer. Every agent correct, and the merchant still wrong. That gap is
what Commons closes.**

---

## Notes for the presenter

**The single strongest line** is `restriction_beats_incentive`. If you are running short,
cut Example 2 and the Rules tab, and spend the time on Example 1.

**Do not claim the agents are LLM-driven during the demo.** They were driven through the
MCP servers directly. The claim that holds is that four independent agents hit one gateway
and got arbitrated, which is the part that matters.

**If someone asks "why not just fix the agents":** because you did not write them. The
merchant installs agents from a marketplace. The whole premise is arbitrating software you
cannot modify.

**If someone asks about latency:** it is a local SQLite read on an indexed column plus rule
evaluation, single digit milliseconds, and the stress harness covers it.

**Numbers you can quote, all from `run_533b126090f0`:** 4 agents, 2 vendors, 13 customers,
71 calls, 15 stopped by Commons, all five rules fired at least once, both branches of the
contradiction rule exercised.
