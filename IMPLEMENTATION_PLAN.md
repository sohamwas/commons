# COMMONS — Implementation Plan

**Written:** 2026-08-24 · **Deadline:** 2026-09-05 (12 days) · **Companion to:** `COMMONS_HANDOFF.md`

Read `COMMONS_HANDOFF.md` first for *why*. This document is *how*, in order, with a
definition-of-done for each day and a contingency for each thing that can go wrong.

---

## 0. Environment reality check (verified 2026-08-24, on this machine)

| Check | Result | Consequence |
|---|---|---|
| Python | **3.13.1** (via `py` launcher; `python` not on PATH) | Use `py -m venv`, then `.venv/Scripts/python.exe`. |
| Node / npm | **25.8.0 / 11.11.0** | Next.js fine. |
| Git | 2.52.0 | **Repo not initialised yet.** Day 0 task. |
| **Go** | **NOT INSTALLED** | Blocks building `razorpay-mcp-server` from source. |
| **Docker** | **NOT INSTALLED** | Blocks the `razorpay/mcp` Docker image. |
| `mcp` Python SDK | **2.0.0** (2026-07-28), installed into `.venv` | API surface verified below — it is exactly the right shape. |
| `https://mcp.razorpay.com/mcp` | **Live**, returns `401` unauthenticated | Reachable. Streamable HTTP. Needs Basic auth. |

### 0.1 The Go/Docker finding, and why it does not matter

Handoff §8.2 assumed cloning and running Razorpay's Go MCP server locally. Neither Go nor
Docker is installed here. **But Razorpay ships a remote MCP server** at
`https://mcp.razorpay.com/mcp` — Streamable HTTP, authenticated with
`Authorization: Basic base64(key_id:key_secret)`, and it **auto-detects test mode from
`rzp_test_` keys**.

Commons is an MCP *client* on its upstream face, so it can speak Streamable HTTP directly to
that endpoint. No `mcp-remote` shim, no Go, no Docker, no install.

The credibility claim from §8.2 is **unchanged and arguably stronger**: approved calls still
hit Razorpay's genuine test API, real payment links still appear in the real Razorpay test
dashboard — and now they travel through Razorpay's own hosted MCP infrastructure rather than a
binary we compiled ourselves.

> **Caveat, and it is the single most important Day-1 check.** Razorpay's docs state the remote
> server restricts *some* write tools relative to local deployment, without publishing the list.
> `create_payment_link` is load-bearing for the demo. **Day 1 spike verifies it empirically.**
> Contingency in §7 (R1).

### 0.2 MCP SDK v2 API surface — verified by introspection, not by docs

The docs site 404s; these were read off the installed package.

```python
# ---- server face (what agents connect to) ----
from mcp.server import Server
srv = Server("commons", on_list_tools=..., on_call_tool=...)   # dynamic handlers — ideal for a proxy
app = srv.streamable_http_app()                                # ASGI app, mountable in Starlette

# ---- client face (what Commons calls upstream) ----
from mcp import Client
from mcp.client.streamable_http import streamable_http_client   # (url, *, http_client=httpx2.AsyncClient)
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.client import InMemoryTransport                 # (server) — in-process, no subprocess
```

Three facts that shape the design:

1. `Server(...)` takes **`on_list_tools` / `on_call_tool` callables**. A generic passthrough proxy
   is a natural fit — no per-tool registration, so Commons never needs to know Razorpay's 55 tools.
2. `streamable_http_client` accepts a **preconfigured `httpx2.AsyncClient`** — that is where the
   Razorpay `Authorization: Basic` header goes.
3. **`InMemoryTransport(server)`** lets a client bind to a `Server` object in the same process.
   This is what makes `commons demo` (no keys, bundled fake Razorpay) free to build — the same
   proxy code, one upstream swapped.

---

## 1. Decisions locked

Handoff §19 left six things open. Five are resolved here. Rationale is given so they can be
reversed knowingly.

| # | Decision | Rationale |
|---|---|---|
| **D1** | **One long-running proxy process. Streamable HTTP. One route per upstream:** `/mcp/razorpay`, `/mcp/messaging`. | Cross-agent state requires **one shared process**. A stdio proxy spawned per agent would give each agent its own private state — which is the exact bug Commons exists to fix. HTTP also makes the Connect screen's one-line URL diff literally true. |
| **D2** | ~~Agent identity via `X-Commons-Agent` header~~ → **REVISED Day 1: agent identity comes from the ROUTE**, `/mcp/{agent}/{upstream}`, one MCP server instance per pair. | SDK v2 gives handlers a `ServerRequestContext` with no access to HTTP headers, so a header would have needed ContextVar plumbing. The route is better anyway: identity is closed over in the handler and cannot be lost or spoofed, and **every agent gets its own onboarding URL** — which is literally the Connect screen's one-line change. |
| **D3** | **Upstreams support 3 transports: HTTP, stdio, in-memory.** Razorpay = HTTP remote (default), stdio Go binary (fallback), in-memory fake (demo tier 1). | Falls out of the SDK for free, and the two-tier setup of §15.4 becomes a config swap rather than a code path. |
| **D4** | **Entity resolution is DECLARATIVE** — a *Tool Semantics Manifest* (§3). Confirms handoff §11's recommendation. | Inference is demo risk with no upside. Declarative is also the honest answer to "how does this work for a third-party agent you can't inspect?" — you need its *tool schema*, not its source. |
| **D5** | **Rule invariants are hardcoded Python primitives (§4). Natural-language authoring is a STRETCH GOAL**, built only if Day 10 arrives early. | Handoff §9 flags NL→invariant compilation as a single point of failure. The UI still shows English beside the compiled invariant — the English is just authored by hand for now. |
| **D6** | **Ledger = SQLite**, written only by the proxy. Exported to `run.json` for replay. | Single writer, zero setup, trivially committable, and the export is the Vercel demo. |
| **D7** | **Persona reactions are LLM-decided (label + text in one call), aggressively cached.** | Preserves handoff §10's "reactive personas with consequences" requirement without blowing the token budget — cache collapses ~80 inbound messages to ~30 distinct contexts. |
| **D8** | **Third MCP server (Shopify-shaped): CUT** unless Day 10 arrives early. | Two servers already prove cross-vendor entity resolution. A third adds narrative, not capability. |
| **Open** | **The name "Commons."** | Still yours to confirm. Everything below uses it; a rename is a find-and-replace, cheap until the Vercel domain is registered on Day 10. |

---

## 2. Repo layout

```
razorpay_buildathon/
├─ README.md                    # THE PITCH DOCUMENT (§15.6) — thesis first, screenshot second
├─ COMMONS_HANDOFF.md           # why (existing)
├─ IMPLEMENTATION_PLAN.md       # how (this file)
├─ ARCHITECTURE.md              # required by submission
├─ .env.example                 # never commit .env
├─ pyproject.toml
├─ commons/
│  ├─ proxy/
│  │  ├─ app.py                 # Starlette: mounts /mcp/{upstream} + /api/* for dashboard
│  │  ├─ face.py                # MCP server face: on_list_tools / on_call_tool
│  │  ├─ upstream.py            # HTTP | stdio | in-memory upstream clients
│  │  └─ registry.py            # agent registry + per-agent tool allowlist (least privilege)
│  ├─ semantics/
│  │  ├─ manifest.py            # loads + validates the Tool Semantics Manifest
│  │  └─ manifests/razorpay.yaml, messaging.yaml
│  ├─ identity/resolver.py      # phone|email|customer_id -> canonical entity
│  ├─ rules/
│  │  ├─ primitives.py          # RateLimit, CumulativeBudget, StateCondition, MutualExclusion, Contradiction
│  │  ├─ engine.py              # evaluate(call, ledger) -> Decision
│  │  └─ ruleset.yaml           # the 4 demo rules
│  ├─ ledger/{db.py,schema.sql,export.py}
│  ├─ world/                    # simulator: clock.py, customers.py, events.py, personas.py
│  ├─ agents/                   # base.py (one OpenAI-compatible loop) + 4 agent prompt/tool configs
│  ├─ llm/{client.py,cache.py,providers.yaml}
│  └─ cli.py                    # commons demo | commons run --seed N --mode observe|enforce
├─ mcp_servers/messaging/       # our messaging MCP server (send_whatsapp, send_email)
├─ dashboard/                   # Next.js — src/lib/datasource.ts is the file|http adapter
└─ runs/seed-4471/run.json      # committed recorded run -> powers the Vercel replay
```

---

## 3. The core abstraction: the Tool Semantics Manifest

**This is the technical contribution. Build it carefully; everything else is plumbing.**

A rule like *"max 15% total discount per customer per 30 days"* needs three things from an
arbitrary tool call that Commons has never seen before:

1. **Which entity** is being acted upon?
2. **What class of action** is this?
3. **What magnitude** does it consume?

Least-privilege systems need none of these — they only ask "may this actor call this tool?"
That is precisely why they cannot express the rules in handoff §6.3. The manifest is where
Commons gets what they lack, and it is **declared per tool, from the tool's public schema** —
so it works for third-party agents whose source you cannot read.

```yaml
# commons/semantics/manifests/razorpay.yaml
upstream: razorpay
tools:
  create_payment_link:
    entity:      {from: args, path: customer.contact, as: phone}
    action_class: discount_grant
    magnitude:   {from: args, path: notes.discount_pct, unit: percent}
    resource:    {from: args, path: notes.order_id}
  payment_link_notify:        # Razorpay's OWN outbound-contact tool — see §5 Day 1 findings
    entity:      {from: upstream_lookup, tool: fetch_payment_link, path: customer.contact, as: phone}
    action_class: promotional_message
  update_order:               # RTO Shield restricting an order to prepaid-only
    entity:      {from: upstream_lookup, tool: fetch_order, path: notes.contact, as: phone}
    action_class: fulfillment_restriction
  fetch_payment:
    action_class: read          # reads are never governed; they still get logged

# commons/semantics/manifests/messaging.yaml
upstream: messaging
tools:
  send_whatsapp:
    entity:      {from: args, path: to, as: phone}
    action_class: promotional_message   # overridden to transactional_message when args.template.kind == "txn"
  send_email:
    entity:      {from: args, path: to, as: email}
    action_class: promotional_message
```

`as: phone` / `as: email` / `as: customer_id` names the **identity namespace**. The resolver
(§D4) folds all namespaces to one canonical `entity_id` via an identity graph seeded by the
world simulator.

> **This is the moment the whole thesis becomes real:** `send_whatsapp(to: "+9198…21")` on the
> messaging upstream and `create_payment_link(customer.contact: "+9198…21")` on the Razorpay
> upstream resolve to the *same* `entity_id`. Two independently-built vendors, one human. No
> per-agent permission system can see that edge, because neither vendor knows the other exists.

**Day 2 must end with a passing test that asserts exactly this.** It is the single most
important unit test in the project.

---

## 4. The rule engine

Five primitives cover all four demo rules and everything in handoff §6.3. Each evaluates a
candidate call against the ledger and returns `ALLOW | DEFER | BLOCK` plus the reason.

| Primitive | Demo rule it implements | Question it asks the ledger |
|---|---|---|
| `RateLimit` | Max 1 outbound message per customer / 24h | count of `action_class` for `entity_id` in window |
| `CumulativeBudget` | Max 15% total discount per customer / 30d | sum of `magnitude` for `entity_id` in window |
| `StateCondition` | No promo to a customer with an open dispute | current entity state flags |
| `MutualExclusion` | One agent per order at a time | is there a live lease on `resource` held by another agent |
| `Contradiction` | RTO Shield's restriction beats Cart Recovery's incentive | declared priority between two `action_class`es on one entity |

```yaml
# commons/rules/ruleset.yaml
- id: msg_frequency
  english: "Never contact the same customer more than once in 24 hours."
  primitive: RateLimit
  scope: {action_class: [promotional_message], per: entity, window: 24h, max: 1}
  on_violation: DEFER          # queue it, don't destroy it

- id: discount_cap
  english: "No customer receives more than 15% total discount in any 30-day period."
  primitive: CumulativeBudget
  scope: {action_class: [discount_grant], per: entity, window: 30d, cap: 15, unit: percent}
  on_violation: BLOCK

- id: no_promo_during_dispute
  english: "Never send promotional offers to a customer with an open dispute."
  primitive: StateCondition
  scope: {action_class: [promotional_message, discount_grant], when: "entity.dispute_status == 'open'"}
  on_violation: BLOCK

- id: one_agent_per_order
  english: "Only one agent may work an order at a time."
  primitive: MutualExclusion
  scope: {resource: order_id, lease: 30m}
  on_violation: DEFER
```

**Engine contract:**
- Evaluate **every** rule, always. Never short-circuit — the ledger must record *all* rules that
  fired, not just the first. The "4 violations" badge in the hero UI depends on this.
- Resolution: strictest wins (`BLOCK` > `DEFER` > `ALLOW`).
- **Mode changes exactly one line of behaviour.** `OBSERVE` records the decision and forwards
  anyway; `ENFORCE` records the decision and honours it. Same engine, same code path. Assert this
  with a test that runs one fixture through both modes and diffs the decision rows — they must be
  **identical**. That test *is* the "one engine, two modes" claim, and a judge can read it in
  thirty seconds.

**Build the engine against synthetic call sequences, not against agents.** Rules are pure
functions of `(call, ledger)`. You can unit-test all four demo rules on Day 3 with hand-written
JSON and zero LLM calls, in milliseconds. Do not wait for the agents to exist.

---

## 5. Day-by-day plan

Each day has a **DoD** (definition of done). If a DoD is not met, do not start the next day —
consult the cut list (§8) instead.

### Day 0 — today, 24 Aug — decisions, keys, scaffold

Two of these only you can do, and everything downstream blocks on them. Do them first.

1. **Razorpay test keys.** Dashboard → Account & Settings → API Keys, mode = **Test**.
   No KYC needed. You want `rzp_test_...` + secret. → `.env`
2. **Free LLM keys.** ~~Cerebras~~ (free tier withdrawn — see §6.1). Groq, Google AI Studio,
   OpenRouter. All no-credit-card. → `.env` **[DONE 24 Aug — all keys verified working]**
3. *(Costs one email, per handoff §16.9)* Ask the buildathon organisers whether participants get
   API credits. Anthropic credits are plausible given Agent Studio is built on the Claude Agent SDK.
4. `git init`, `.gitignore` (`.env`, `.venv`, `node_modules`, `*.db`), first commit.
5. Draft the README **thesis paragraph** now, while the argument is fresh. Not the whole README —
   the two sentences from handoff §20 that go above the fold. Everything you build gets measured
   against whether it makes those two sentences visible.

**DoD:** `.env` has 5 working keys; repo initialised; thesis paragraph written.

---

### Day 1 — ✅ DONE 24 Aug (a day early) — proxy skeleton + THE SPIKE

**Spike results — `scripts/spike_razorpay_mcp.py`, fixture at `fixtures/razorpay_remote_tools.json`:**

- Connected: `razorpay-mcp-server v1.0.0`, protocol `2025-06-18`, Basic auth with `rzp_test_` keys.
- **42 tools exposed remotely** (local build has 55) — so 13 are restricted, and Razorpay
  still does not publish which.
- **`create_payment_link` PRESENT and working.** **R1 does not trigger.** No Go, no Docker needed.
- **`create_refund` ABSENT** remotely. Checked against §4: **none of the four demo rules need it**,
  so the demo is unaffected. `fetch_refund` / `update_refund` are present if refund state is ever
  wanted. Dispute Responder's allowlist was written around this.
- **Unplanned find: `payment_link_notify` is an outbound customer-contact tool inside Razorpay's
  own MCP.** This is genuinely useful — the frequency rule can now be breached by *Razorpay's own
  tool plus our messaging server*, so the cross-vendor collision no longer depends solely on a
  server we wrote. Strengthens the demo's credibility. Added to the manifest in §3.
- Live write confirmed: `plink_TTh3z9D4kmWGte`, ₹4,200, visible in the Razorpay test dashboard.

**Skeleton results — `commons/proxy/`, verified by `scripts/verify_proxy.py`:**

- 4 endpoints live, one per agent, all sharing **one** upstream connection (D1).
- Least privilege at the face: `cart-recovery` sees **3 of 42** tools.
- Out-of-scope call (`update_order`) refused **by Commons**, before it reaches Razorpay.
- In-scope write forwarded to the real test API: `plink_TThDBbAAWf1dND`.
- One gotcha worth remembering: Starlette's `Mount` regex requires the remainder to start with
  `/`, so a bare endpoint path 307-redirects and MCP clients fail with "Unexpected content type".
  Replaced with an explicit `PathDispatch` so the URL works without a trailing slash.

**Remaining Day 0 item:** `git init` + first commit (not done — your call on repo setup).

---

### Day 1 (original plan, for reference) — proxy skeleton + THE SPIKE

Handoff §18 is right that the proxy comes first: it de-risks the MCP plumbing before anything
sits on top. But do the spike *before* the skeleton, because the spike can change the plan.

**Spike first (60–90 min), in this order:**
```
a. Connect to https://mcp.razorpay.com/mcp with Basic auth + rzp_test_ keys.
b. tools/list  -> record the exact tool set the REMOTE server exposes. Commit it as a fixture.
c. tools/call create_payment_link -> does it succeed?
d. Open the Razorpay test dashboard. Is the link actually there?
```
Step (c) is the fork in the road. If it fails → §7 R1.

**Then the skeleton:**
- Starlette app mounting `Server(...).streamable_http_app()` at `/mcp/razorpay` and `/mcp/messaging`.
- `on_list_tools` → fetch upstream tools, filter by the calling agent's allowlist, return.
- `on_call_tool` → forward verbatim, return verbatim. **No rules yet. Pure passthrough.**
- `X-Commons-Agent` header → agent id; reject unknown agents.

**DoD:** a plain MCP client, pointed at `http://localhost:8787/mcp/razorpay` with an agent header,
creates a **real payment link visible in the Razorpay test dashboard**. Screenshot it — that
screenshot is going in the video, and it is the proof that nothing here is mocked.

---

### Day 2 — ✅ DONE 25 Aug — semantics, identity, ledger

**Built:** `commons/semantics/` (manifest + extraction), `commons/identity/resolver.py`,
`commons/ledger/` (schema + queries), wired into the proxy's call path.

**DoD met twice — in tests and on the live path:**

- `pytest` — **18 passing**, including the cross-vendor resolution test from §3.
- `scripts/verify_ledger.py` — two different agents, through Commons, against the **real
  Razorpay test API**, writing the customer's phone in two different formats:

  ```
  cart-recovery          discount_grant  +919800000021  ent_23619c84a0  10.0%
  subscription-recovery  discount_grant  +919800000021  ent_23619c84a0   8.0%
  distinct entities touched: 1
  CUMULATIVE DISCOUNT ACROSS ALL AGENTS: 18.0%
  ```

  Two payment links really exist in the Razorpay test dashboard. Neither agent can see
  the other. The ledger sees both. **That is the entire thesis, working, on day two.**

**Findings that changed the code:**

- **Razorpay's MCP input schemas are FLAT** (`customer_contact`, `notify_sms`) while its API
  *responses* are nested (`customer.contact`). The Day 1 spike used the nested shape, so those
  first links were created with no customer attached. Fixed in the manifests and both scripts.
  Worth re-checking whenever a manifest path is written — read the schema, don't infer it.
- **Razorpay rejects spaces in `contact`** ("length must be between 8 and 14"), so the
  demo uses two formats the vendor itself accepts — full E.164 from one agent, the bare
  10-digit subscriber number from the other. Still exercises normalisation, and is more
  realistic than a format Razorpay would have refused anyway.
- Tools with **no manifest entry are logged loudly and forwarded ungoverned** rather than
  silently passing. A manifest gap is a real hole in coverage and should look like one.

---

### Day 2 (original plan, for reference) — semantics, identity, ledger

- Tool Semantics Manifest loader + validation (§3).
- Identity graph in SQLite: `(namespace, value) -> entity_id`. Phone normalisation to E.164.
- Ledger schema: `run`, `event`, `call`, `decision`, `rule_fired`, `entity`, `entity_state`.
  Store full request args and response blobs — handoff §17.4 promises every violation ships with
  a replayable trace, and you cannot reconstruct it later.
- Every proxied call now writes a `call` row with a resolved `entity_id`. Still ALLOW-everything.

**DoD:** the cross-vendor resolution test from §3 passes — a `send_whatsapp` to a phone number and
a `create_payment_link` for a customer id land on the **same `entity_id`** in the ledger.

---

### Day 3 — 27 Aug — rule engine

- The five primitives (§4). Pure functions over `(call, ledger)`.
- `ruleset.yaml` loader; engine evaluates all rules and records every one that fired.
- OBSERVE / ENFORCE modes.
- **Unit tests with hand-written call sequences.** Every demo rule gets a violating fixture and a
  compliant fixture. No LLM, no agents, no world — milliseconds.
- The identical-decisions-across-modes test (§4).

**DoD:** `pytest` green. Rule violations are provable from fixtures alone, before a single agent exists.

---

### Day 4 — 28 Aug — messaging server + world simulator core

- `mcp_servers/messaging`: `send_whatsapp`, `send_email`. Runs in-process (`InMemoryTransport`)
  **and** standalone. Delivery is simulated; it writes to the world's contact log.
- World simulator: seeded RNG, priority-queue event clock, customer state objects
  (subscription, cart, dispute history, contact log, lifetime discount).
- Event generators: cart abandonment, UPI Autopay mandate failure, dispute filing, COD RTO risk.
- **Calibrate to published rates and cite them inline in the code** (handoff §10, §17.3):
  UPI Autopay success 30–50%, Indian COD RTO rates, cart abandonment rates. A comment with a
  URL next to each constant costs nothing now and is worth a lot in a judge's eyes.

**DoD:** `commons world --seed 4471 --days 30` prints a deterministic event log. Same seed twice →
byte-identical output.

---

### Day 5 — 29 Aug — personas and consequences

- ~20 customers **sampled for concurrent conditions** (handoff §16.5) — and disclose the sampling
  in the README, precisely: *the population is sampled for overlap; the agents are not designed
  to collide.*
- Persona reaction: one cached LLM call returns `{reaction, text}` where reaction ∈
  `engage | ignore | irritated | opt_out | escalate`.
- **Reactions must have consequences** (explicit handoff §10 requirement): `opt_out` suppresses
  future contact; `irritated` lowers conversion probability; `escalate` opens a dispute. A counter
  that ticks with no downstream effect is not a reactive persona.

**DoD:** a run where the 3rd message to one customer measurably changes the world's trajectory.

---

### Day 6 — 30 Aug — the four agents, first full OBSERVE run

- One `agents/base.py`: OpenAI-compatible chat-completions loop with tool calling. **Every
  provider uses it** — Groq and OpenRouter are OpenAI-compatible, and Gemini exposes one at
  `https://generativelanguage.googleapis.com/v1beta/openai/` (verified: tool calling works).
  One code path, N model configs — see the allocation table in §6.2.
- Four agents built **strictly to Razorpay's published job descriptions**: Cart Recovery,
  Subscription Recovery, Dispute Responder, RTO Shield.
  **Do not design them to collide** (handoff §12, §17.5). Collisions come from the customer
  population, never from the agent prompts. Write that constraint as a comment at the top of each
  agent file so it survives a late-night edit.
- Per-agent tool allowlist: 2–3 tools each, not 55 (handoff §16.3 — and pleasingly, this is
  least privilege, the principle Commons is built to complement).
- LLM cache keyed on `sha256(agent, model, system_prompt, compact_context)` (handoff §16.4).
- Malformed tool calls logged to a **separate bucket from violations** (handoff §16.7) so
  weak-model noise never pollutes the headline number.

**DoD:** full 30-day OBSERVE run completes. Ledger contains real violations. Token spend inside
free tiers.

---

### Day 7 — 31 Aug — ENFORCE run, A/B, and the honesty pass

**This is the day the thesis is either demonstrated or it isn't. Buffer is deliberately here.**

- ENFORCE run, same seed. Verify: 2nd message deferred, discount capped at 15%, promo to disputing
  customer blocked, RTO Shield's restriction beating Cart Recovery's incentive.
- **Write down the determinism caveat now, before you forget it, and put it in the README:**
  same seed gives the same *world*, and the two runs are identical **up to the first
  intervention**. After that, agent behaviour legitimately diverges — that divergence *is* the
  effect being demonstrated. Claiming byte-identical traces across modes would be false, and a
  sharp judge will check.
- Compute the headline numbers: violations per run, margin saved, messages suppressed.

**DoD:** two runs, same seed, quantified difference. If collisions are too rare → §7 R2.

---

### Day 8 — 1 Sep — dashboard: hero + ledger

- Next.js, dark-first, monospaced numerals, **red reserved exclusively for violations**. Fintech
  infrastructure, not purple-gradient AI product (handoff §13.3).
- `src/lib/datasource.ts` — one adapter, two backends (`file:` committed JSON, `http:` live proxy).
  Build this on Day 8 even though only one backend is needed; retrofitting it on Day 10 is worse.
- **Customer timeline (hero).** Four agent lanes converging on one human, violations rendered
  *between* the lanes (handoff §13.1). This is the screen that carries the whole idea.
- **Conflict ledger.** Chronological ALLOW/DEFER/BLOCK, rule fired, agents involved, expandable
  to full trace.

**DoD:** Priya's timeline renders from real ledger data with all four violations visible.

---

### Day 9 — 2 Sep — dashboard: the rest

- **Fleet overview + agent-count slider** (1→4 agents, violations climbing superlinearly).
  Handoff §13.2 calls this the highest-value non-hero screen; it is the thesis in one image.
  Needs 4 pre-computed runs — generate them overnight after Day 8.
- Run comparison (A/B on the same seed), with **run 2's blocked actions ghosted onto run 1's
  timeline** — pure rendering over data you already have (handoff §13.1).
- Rules page: English beside compiled invariant, live per-rule compliance rate.
- Connect screen: the one-line diff.
- **Visible `OBSERVE > ENFORCE` toggle in the header** — proves one-engine-two-modes at a glance.

**DoD:** every Must and Should screen from handoff §13.4 renders.

---

### Day 10 — 3 Sep — export, Vercel replay, README

- `commons export --run <id> > runs/seed-4471/run.json`. Commit it.
- Deploy dashboard to Vercel in `file:` mode. **Zero backend, zero LLM calls, zero cost.**
- Deep link `?seed=4471&customer=4471` that lands cold-email readers *inside* the timeline —
  no hero section, no scrolling, no decision (handoff §15.5).
- Label it honestly: *"replay of a recorded run — seed 4471."*
- **Finish the README.** Selection is "code evaluation only," so the README **is** the
  application. Thesis → timeline screenshot → architecture → setup. Never setup first.
  Include, in this order, the four things a sharp judge will go looking for:
  - why self-hosting is correct rather than thrifty (§15.1);
  - why model quality is orthogonal to the finding (§16.8);
  - that the agents were not designed to collide, and the population was sampled for overlap;
  - the limitation, stated in your own words before anyone else states it for you (§17.6).

**DoD:** public URL loads the replay in under 3 seconds.

---

### Day 11 — 4 Sep — architecture doc + video

- `ARCHITECTURE.md` — required by the submission.
- Record the 5-minute video to the script in handoff §14. Non-obvious ordering advice: record
  **the reveal (four green per-agent dashboards) immediately after the OBSERVE run**, while the
  contrast is loudest. That 30 seconds is the money shot; everything else is setup for it.
- Close on the generalisation (Mastercard's 3 × ₹50,000 arithmetic) so it does not read as a
  payments-only problem.

**DoD:** video under 5:00, uploaded, linked in the README.

---

### Day 12 — 5 Sep — submit

Buffer. Submit early in the day, not late. If Days 1–11 slipped, this is the day the cut list (§8)
pays for itself.

---

## 6. Provider allocation and token budget

### 6.1 Handoff §16.2 is stale — measured against the real accounts, 2026-08-24

Probed with `scripts/probe_providers.py` against the actual keys. Three of the four assumptions
in handoff §16.2 were wrong:

| Provider | Handoff assumed | **Measured reality** | Verdict |
|---|---|---|---|
| **Cerebras** | ~1M tokens/day, best budget | **`402 Payment Required` on both models** (`gemma-4-31b`, `gpt-oss-120b`). Free tier is gone. | **DEAD. Removed.** |
| **Groq** | `llama-3.3-70b-versatile`, 1K RPD / 12K TPM | Model **retired** — no Llama in the catalog. Tool-capable: `openai/gpt-oss-120b`, `openai/gpt-oss-20b`. `qwen3.6-27b` **does not emit tool calls**. Limits: **1000 RPD, 8000 TPM**. | Usable, one agent. TPM is the throttle. |
| **OpenRouter** | ~20 RPM per model, spreadable | Account is `is_free_tier: true` → **50 requests/day, account-wide**, not per model. 14 free models advertise tools; `nemotron-3-super-120b` and `nemotron-3-ultra-550b` confirmed emitting real tool calls. | Not a workhorse. **Repurposed** — see §6.3. |
| **Gemini** | 10–15 RPM, "conservative" | `gemini-2.5-flash` retired (404), but **six current flash models all tool-call successfully**: `2.5-flash-lite`, `3-flash-preview`, `3.1-flash-lite`, `3.1-flash-lite-preview`, `3.5-flash-lite`, `flash-lite-latest`. Quotas are **per-model, per-project** → each is a **separate bucket**. | **Strongest provider we have.** |

**Google was the worry and turns out to be the backbone.** Not because its per-model limits are
generous — they are not, and Google no longer publishes them (they are per-project, visible only
at `aistudio.google.com/rate-limit`) — but because **six independent buckets beat one large one**
when the workload splits cleanly across five consumers.

### 6.2 Allocation

| Consumer | Provider | Model | Rationale |
|---|---|---|---|
| Cart Recovery | Groq | `openai/gpt-oss-120b` | Highest-volume agent on the fastest inference. |
| Subscription Recovery | Gemini | `gemini-3.1-flash-lite` | Own bucket. |
| Dispute Responder | Gemini | `gemini-3-flash-preview` | Own bucket; strongest reasoning of the flashes, and disputes are the hardest task. |
| RTO Shield | Gemini | `gemini-2.5-flash-lite` | Own bucket; lowest-volume agent. |
| **Personas** | Gemini | `gemini-3.5-flash-lite` | Own bucket. Highest request count of all five — one call per inbound message. |
| **Frontier control run** | OpenRouter | `nvidia/nemotron-3-ultra-550b-a55b:free` | 550B params, 1M ctx. 50/day is *ample* for one control run. |
| Overflow / fallback | Groq | `openai/gpt-oss-20b` | Assume Groq's bucket is **shared across models** (conservative); treat as failover, not capacity. |

Still a heterogeneous fleet — three vendors, six distinct models — so handoff §16.2's
"real marketplaces won't be single-vendor" story survives intact.

### 6.3 OpenRouter's 50/day cap is an asset, not a loss

Handoff §16.8 says a single comparison run on a frontier model, showing the violation persists,
would "nail shut" the objection that these findings are weak-model artifacts — *"worth doing, not
worth blocking on."*

50 requests/day is useless for a workhorse and **exactly right for that control run**.
`nemotron-3-ultra-550b` is a 550B-parameter model and it emits clean tool calls. So on Day 7,
re-run **one customer's timeline** through it and show the same collision occurs.

That converts §16.8 from a README paragraph asking to be believed into a result. Do it on Day 7
while the A/B is fresh — it is ~15 requests, well inside the cap.

### 6.4 Budget

- **Groq is throttled by TPM, not RPD.** 8,000 TPM ÷ ~3K tokens per invocation ≈ **2.6 invocations
  per minute**. One agent's ~20 invocations per run ≈ 8 minutes. Fine for a sequential simulation;
  it does mean **do not parallelise the agents on Groq**.
- **The ENFORCE run costs more than the OBSERVE run.** After the first intervention agents see
  different state, cache keys change, hit rate drops. **Budget ~2× for the A/B pair.**
- **Day 9's agent-slider needs 4 more runs.** Run them overnight after Day 8, not an hour before
  a deadline.
- **Re-probe before Day 6.** These limits moved twice in the last year; `scripts/probe_providers.py`
  exists so re-checking costs one command.

---

## 7. Risk register

| | Risk | Likelihood | Mitigation / contingency |
|---|---|---|---|
| **R1** | ~~**Remote Razorpay MCP restricts `create_payment_link`.**~~ **RESOLVED 24 Aug — it works.** `create_refund` is restricted but no demo rule needs it. | Closed. | Detected Day 1 by the spike, which is why it is first. Fallback, in order: (a) use a permitted write tool instead — `create_order` or `create_refund` carry the demo equally well; (b) `winget install GoLang.Go`, `go build`, run the official server over **stdio** — the upstream abstraction (D3) already supports this, so it is a config change, not a rewrite. |
| **R2** | **The agents don't collide** — the anti-circularity rule (handoff §12) forbids designing them to. | Medium. **The real project risk.** | Legitimate lever: turn up **customer-population overlap**, which is world config, not agent design, and disclose the rate. Illegitimate lever: editing agent prompts to induce collisions — this destroys the finding, so don't. If overlap at a *disclosed and plausible* rate still yields no collision, that is itself an honest result and the README should say so; but ~20 customers sampled for concurrent conditions makes it unlikely. |
| **R3** | **Weak free models call tools unreliably.** | High. | Use only models **measured** to emit tool calls (§6.1) — `gpt-oss-120b`, the Gemini flash family, `nemotron-3-*`. Note `qwen3.6-27b` fails this and is excluded. Validate-and-retry on malformed calls. Log malformed calls **separately from violations** so they never contaminate the headline metric (handoff §16.7). |
| **R4** | **Free-tier rate limits stall a run mid-way.** | Medium-high — the surface shrank when Cerebras died. | Limits are **per-project / org-level**, so extra keys don't help; **separate models do** (§6.1). Spread across six Gemini buckets + Groq. Exponential backoff on 429. **Checkpoint the ledger** so a stalled run resumes instead of restarting — this is the mitigation that actually matters. |
| **R7** | **A provider dies mid-project, as Cerebras already did.** | Medium — it happened once in 12 days. | Provider is one line of config per agent (§6.2), never hardcoded. `scripts/probe_providers.py` re-verifies the whole fleet in one command. If Gemini tightens, fall back to Groq `gpt-oss-20b` and reduce the customer population before reducing agent count. |
| **R5** | **Dashboard eats the schedule.** | High — it always does. | Days 8–9 are hard-capped. The Must list (timeline, ledger, A/B) ships; the Should list is genuinely optional. A rough hero screen beats a polished settings page. |
| **R6** | **A judge reads the demo as staged.** | Medium. | Handoff §17 in full, and put the anti-circularity rule **on screen in the video**, not just in the README. Naming your own limit reads as confidence. |

---

## 8. Cut list, in order

When you fall behind — and you will — cut from the top:

1. Third MCP server (already cut, D8)
2. Natural-language rule authoring (already a stretch goal, D5)
3. Rules page compliance rates
4. Fleet overview + agent slider — *cut only if Day 9 is truly lost; it is the thesis in one image*
5. Run-comparison screen — the A/B still works as two screenshots in the video
6. `commons demo` tier-1 bundled-fake path — nice for adoption, not for judging

**Never cut:** the customer timeline, the conflict ledger, the ENFORCE run, or the README. Those
four are the submission. Everything else is supporting material.

---

## 9. What to do right now

The first three are yours alone and everything else blocks on them:

1. Generate `rzp_test_` keys.
2. Sign up for Groq, Cerebras, Google AI Studio, OpenRouter.
3. Email the buildathon organisers about API credits.

Then say the word and I'll start Day 1 — spike first, skeleton second.
