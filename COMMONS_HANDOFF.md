# COMMONS — Project Handoff Document

**Written:** 2026-08-24
**Purpose:** Full context handoff to a fresh Claude Code session. Everything below was established across a long ideation conversation. Read Sections 0–6 before proposing anything; Section 5 lists ideas already killed and why, so they are not re-proposed.

---

## 0. TL;DR

**Commons** is an MCP-layer proxy that enforces policy on the **entity being acted upon** (the customer) rather than the **agent doing the acting**.

It runs in two modes over one rule engine:
- **Simulate** — run a fleet of agents against a synthetic customer population, report every policy violation before anything real is touched.
- **Enforce** — the same rules run live against real MCP servers, blocking violations instead of reporting them.

**One-line thesis:** *Every agent platform in 2026 scopes permissions to the agent. None scope limits to the customer. The moment you run more than one agent, your real exposure lives somewhere nothing can see.*

**Stack:** Python (proxy, rule engine, simulator, agents) + Next.js (dashboard). Deployed demo on Vercel; tool itself is self-hosted via clone.

---

## 1. Context and Goals

The user is a student who needs:

1. **A portfolio project** impressive enough to cold-email well-established Bangalore startups. Bar is high on both novelty and execution.
2. **A Razorpay AI Buildathon submission** (Open Track).
3. The project should solve a genuinely recurring problem and be **a tool other people can use**.
4. Original interest area was LLM observability/evaluation, or an emerging subfield of agentic AI.

Both goals are served by the same build. The project must **not** read as Razorpay-specific — see Section 20 for pitch variants aimed at non-Razorpay audiences.

---

## 2. Hard Constraints

| Constraint | Detail |
|---|---|
| **Deadline** | Buildathon applications close **5 September 2026**. As of writing: **12 days**. |
| **Eligibility** | Students only. User is a current student — eligible. |
| **Budget** | **Zero.** No paid LLM APIs, no paid hosting. See Section 16. |
| **Stack** | Python backend + Next.js frontend (user's choice). |
| **Platform** | Windows 11, PowerShell primary, Bash available. |
| **Submission** | Public repo + 5-minute pitch video + architecture documentation. |
| **Selection** | *"No resume screening, aptitude tests, or group discussions. Code evaluation only."* The repo **is** the application. |
| **Program** | ₹75,000/month stipend, 6 or 12 months, in-person Bangalore from September. |

**Buildathon tracks:** 01 AI Growth & Agentic Commerce, 02 AI Risk Manager, 03 AI Revenue Recovery, 04 AI Finance Controller, 05 Open Track. **Submitting to Track 05 (Open)**, but the writeup should be legible to Track 01 and 02 judges.

---

## 3. Research Findings — Razorpay

### 3.1 Vulcan (foundation model)
- *"India's first transformer-based AI Foundation Model for Payments."*
- Claims: 8–10% improvement in success rates; 5× more disputed transactions identified; 8× more international card fraud detected; "millions of checkouts hyper-personalised."
- **CRITICAL: Vulcan is NOT an LLM.** It is a transformer over transaction sequences. It has no prompts. LLM observability tooling has literally nothing to attach to it. Do not build anything targeting Vulcan.

### 3.2 Agent Studio (launched 12 March 2026)
- A **B2B agent marketplace** built on **Anthropic's Claude Agent SDK**.
- Started with 4 agents, now **8+**: Abandoned Cart Conversion, Dispute Responder, Subscription Recovery (with ElevenLabs), Cashflow Forecaster, RTO Shield, others.
- One-click deploy; merchants can also customise prebuilt agents or build their own.
- **No-Code Agent Builder is in beta** — merchants define "workflows, guardrails, and triggers."
- Pricing: early access, 30-day free trial. *"Some agents may charge per action, some may have a monthly fee, and some may charge only when they deliver results."*
- **Stated future direction (important):** *"third-party builders **will be able to** create and publish specialized agents"*; an *"open ecosystem for developers and fintech partners."*
- Integrations: Shopify, WhatsApp, Shiprocket, Slack, QuickBooks. Agentic commerce extended to Zomato, Swiggy, PVR Inox, Vodafone Idea.

### 3.3 Agentic Experience Platform
Agentic Onboarding (30–45 min → ~5 min), Agentic Dashboard (natural language ops), Agentic Integration (<10 min, works with Claude Code and Replit).

### 3.4 Razorpay MCP Server
- **Open source:** https://github.com/razorpay/razorpay-mcp-server
- Write tools: `create_refund`, `initiate_payment`, `create_order`, `create_payment_link`, `create_payment_link_upi`, `create_instant_settlement`, `create_registration_link`, `create_qr_code`, `close_qr_code`.
- Read tools: fetch payments, orders, refunds, settlements, payouts, payment methods.
- Remote server intentionally restricts some write ops; local deployment required for those. Read-only mode available.
- **NO messaging tools.** No WhatsApp, no email. This matters — see Section 8.3.

### 3.5 Razorpay test mode (verified)
- **No KYC required.** Docs: *"You can start integration immediately without KYC completion."*
- Test keys begin with `rzp_test_`. Generate via Dashboard → Account & Settings → API Keys, with mode set to Test.
- Simulated transactions only, no real money. Test cards available for success/failure/decline scenarios.
- **This means the real Razorpay MCP server can be run locally against the real test API at zero cost.**

### 3.6 Razorpay's published guardrails (VERBATIM — critical)

From https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/

> "Before activation, the merchant reviews and approves exactly what data the agent can access, what actions it can take, and where it needs human approval before proceeding."

> "Every agent action passes through Razorpay's platform-level validation layer before execution. These checks cover: **Compliance boundaries** — the action must fall within regulatory and policy limits. **Amount validation** — payment amounts, discount values, and financial calculations are verified against the merchant's configuration. **PII handling** — personal data is processed in accordance with data protection requirements and the merchant's consent framework. **Scope checks** — if an agent attempts something outside its approved permissions, the action is blocked before it executes. **Out-of-scope behavior detection** — the platform monitors for actions that don't match the agent's intended function and blocks them."

> "Any agent can be configured in **review-first mode**: the agent does all the work — gathers evidence, drafts a response, builds the case — but holds it for the merchant to review before anything is submitted or sent."

> "Every single action is logged with a full audit trail. The merchant can see exactly what the agent did, when, and why — at any time from the agent's performance dashboard."

Also: agents cannot invent discounts (must come from merchant's existing coupon config); no irreversible action without explicit merchant approval; double confirmation for large transfers; consent suppression ("a no is a no"); merchants can kill any agent instantly; Razorpay prohibits dark patterns per India's 2023 Guidelines; "agent certification includes automated screening for problematic communication patterns pre- and post-launch."

**Confirmed ABSENT from all Razorpay material** (guardrails post, platform post, launch post):
- Any testing, simulation, dry-run, or preview of agent behaviour before deployment.
- Any mention of multiple agents running together, cross-agent limits, or cumulative/aggregate limits across agents or over time.
- Any published certification criteria for third-party agents.

### 3.7 Other relevant Razorpay context
- Razorpay + Sarvam AI: AI agent-powered payments (March 2026).
- 400+ documented API endpoints, `llms.txt` in developer docs.
- Medianama published a critical piece raising dark patterns and price discrimination concerns about Agent Studio (URL 403s to WebFetch; searchable).

---

## 4. Research Findings — Competitive Landscape

### 4.1 LLM observability — SATURATED, DO NOT ENTER
Langfuse (acquired by ClickHouse Jan 2026), LangSmith, Braintrust, Arize Phoenix, Comet Opik, Laminar, Latitude, Helicone, Traceloop. The one gap the comparison literature names is "closing the production trace → annotated failure → tracked issue → auto-generated eval → regression test loop," and multiple vendors are actively chasing it.

### 4.2 AI red teaming / adversarial testing — SATURATED
General Analysis, Straiker, Confident AI, promptfoo, garak. They cover OWASP Agentic Top 10, MCP testing, multi-step exploit chains, CI/CD release gates.

### 4.3 Financial agent adversarial benchmarks — TAKEN
- **FraudBench** (arXiv 2608.18136, Aug 2026) — the closest prior art. Executable framework built on τ²-bench dual-control, shared mutable account state, **deterministic state-based grading**, 698-document policy corpus, 107 public scenarios, money-mule and first-party fraud. Results: 49–65% attack-security across four frontier agents.
- **AgentDojo** — 97 tasks, 629 security test cases across email/banking/travel/workspace.
- **StakeBench** — unintended purchases and order tampering in online shopping.
- **WASP** — web agent prompt injection; attacks partially succeed up to 86%.
- **CrAIBench** — Web3, 150+ tasks, 500+ attack cases.
- **τ-bench / τ²-bench** (Sierra) — tool-agent-user interaction, retail and airline domains.

### 4.4 Deterministic evaluation — ALREADY PUBLISHED
- **GroundEval** (arXiv 2606.22737) — "A Deterministic Replacement for LLM-as-Judge in Stateful Agent Evaluation." Motivating result: two frontier judges scored a response 0.85+ where the agent had never retrieved the artifact its answer depended on; deterministic score 0.000.
- **EnvSimBench** — replaces LLM-generated labels with programmatically verified ground truth.

### 4.5 Agent guardrails / runtime enforcement — CROWDED
Starfort (AIM Intelligence), CalypsoAI (F5), Credo AI Agent Governor (July 2026), MintMCP Guardrails, Galileo. Typical latency budget 200–300ms.

### 4.6 Agent control planes / orchestration — CROWDED BUT MISSES OUR CASE
- Galileo open-sourced **Agent Control**, an OSS control plane.
- /dev/agents (ex-Google/Meta/Stripe) building an "operating system for AI agents."
- IBM, Activant, and others on "agent mesh."
- Documented conflict-resolution patterns: voting, consensus, single-writer, event-driven handoff.
- **They all assume you built the fleet.** A supervisor routes tasks to sub-agents you designed together, sharing state you defined. That is not the marketplace case.

### 4.7 MCP gateways — EXIST, BUT BUDGET THE WRONG THING
MintMCP, Tyk, agentgateway, Composio, Preloop. They do auth, RBAC, filtered tool discovery, rate limits, and budgets — **but the budgets are for tokens, model spend, and API call counts, scoped per-agent or per-team.** Infrastructure cost, not business exposure. None can answer a question about the entity being acted upon.

### 4.8 Agentic commerce protocols (context, not our scope)
- **x402** (Coinbase) — most production traction. V2 Dec 2025, Stripe integrated on Base Feb 2026, Cloudflare and AWS edge support. x402 Foundation launched under Linux Foundation July 2026 with 40 members (Coinbase, Cloudflare, Stripe, Visa, Mastercard, AWS, Google).
- **AP2** (Google, 60+ partners) — cryptographically signed mandates, early adoption.
- **ACP** (OpenAI/Stripe), **UCP**.
- McKinsey: agentic commerce could influence $3–5T in global commerce by 2030.

### 4.9 Agentic commerce fraud context
- Visa: **>450% increase** in dark web mentions of "AI Agent" in H1 2026 vs prior six months.
- **69% of merchants** experienced AI-enabled fraud in the past year; only **3%** felt well prepared.
- Akamai: commerce is the epicentre for AI bot attacks and agentic fraud in 2026.
- "Clean fraud" problem: compromised agent transactions look identical to normal agent behaviour.

---

## 5. Ideas Considered and REJECTED — do not re-propose

| # | Idea | Why it was killed |
|---|---|---|
| 1 | LLM observability / eval platform for Razorpay | Market saturated (4.1). Vulcan is not an LLM so there is nothing to trace. Razorpay already ships full audit trails and per-action dashboards for Agent Studio. |
| 2 | Pre-production adversarial stress-test harness ("Blast Radius" / "Ledgerproof") | Substantially **is FraudBench** (4.3) — executable, deterministic state grading, policy-grounded financial agents. Plus overlaps General Analysis et al. (4.2). User correctly identified it as "just stress testing." |
| 3 | Fork/counterfactual replay for causal localisation of the pivotal turn | User rejected the framing as an academic trick bolted onto a security tool. Also GroundEval/EnvSimBench already published the deterministic-oracle idea. |
| 4 | Delayed-label evaluation for Vulcan-style risk models | Not agentic; ML monitoring. Needs data the user doesn't have. Razorpay's risk team owns it. Weak demo. |
| 5 | Off-policy / counterfactual evaluation of payment routing | **Adyen already published it** (arXiv 2501.10470, "Off-Policy Evaluation for Payments"). Also "Maximizing Success Rate of Payment Routing using Non-stationary Bandits" (arXiv 2308.01028). Requires propensity logging that production systems usually lack. Circular if demonstrated on self-generated simulation. Not demoable. |
| 6 | Incrementality / causal attribution for revenue agents ("did the agent actually cause it?") | Strong idea, genuinely novel, ties to Razorpay's outcome-based pricing. **User chose not to pursue** — too causal-inference-flavoured, drifts from agentic AI. Kept on record as the best alternative if Commons collapses. |
| 7 | Marketplace certification ("App Store review for agents") | Kept collapsing back into stress testing (#2). Same FraudBench overlap. Useful fragment salvaged: *certification decays* — a new Claude version silently changes every certified agent's behaviour, and nobody re-certifies. |
| 8 | UPI Autopay retry intelligence | UPI Autopay success is 30–50% (real, quantified pain) but this is an ML problem on Razorpay's turf, their Subscription Recovery agent already exists, and the user has no data. |
| 9 | Dark-pattern / price-fairness auditor for agentic commerce | Real and India-specific (2023 Dark Patterns Guidelines, RBI ODR), but compliance tooling demos poorly and the signal is subtle. |
| 10 | Merchant-side defence against inbound buyer agents | Track 01-shaped and interesting, but it's infrastructure that's hard to demo without real traffic. |
| 11 | AP2/x402 conformance + mandate-chain verification | Very early; Razorpay hasn't publicly committed to either protocol, so it risks landing as irrelevant to them. |

---

## 6. The Thesis (and the evidence behind it)

> **Every agent platform in 2026 scopes permissions to the agent. None scope limits to the person being acted upon. The moment an organisation runs more than one agent, its real exposure lives somewhere nothing can see.**

### 6.1 Per-agent scoping is INTENTIONAL and CORRECT
This was checked deliberately. It descends from **least privilege** and is industry consensus in 2026: Microsoft Entra Agent ID, Okta, AWS Well-Architected (GENSEC05-BP01), Cequence, Arthur. Agents are treated as first-class identities; scoping limits prompt-injection blast radius.

**Do not pitch this as a Razorpay mistake.** It is correct design and should stay. Commons sits **alongside** least privilege, not instead of it.

### 6.2 The distinction that creates the gap

| | Question asked | Nature |
|---|---|---|
| Least privilege | *"May this actor do this?"* | Authority. Per-actor. Stateless. |
| Commons | *"Has too much happened to this object?"* | Accumulation. Per-entity. Stateful. |

No access-control system in fifty years answers the second question — not RBAC, ACLs, IAM, or OAuth scopes. Partitioning by actor is the *definition* of access control. Permission systems are structurally amnesiac about history.

### 6.3 Two kinds of rule

| Checkable from one action (Razorpay does these well) | Needs history + aggregation (nobody can express these) |
|---|---|
| "Is this discount ≤ 20%?" | "Does this 10%, plus the 10% another agent gave last week, breach the monthly cap?" |
| "Is this amount within config?" | "Is this the 4th message to this customer today?" |
| "Is this action in scope?" | "Is another agent already working this order?" |
| "Is PII handled correctly?" | "Have we refunded more than we captured, across all agents?" |

Analogy: a card that declines any single purchase over ₹10,000 does not stop fifty purchases of ₹9,000. A bouncer checking IDs perfectly enforces "nobody under 21" but cannot enforce "no more than 200 inside" unless someone is counting.

### 6.4 Supporting evidence — OWASP already names the failure mode
OWASP's 2026 agentic material states: *"multiple agents must compete for finite shared resources... when each agent optimizes for its own task success without sufficient coordination or global capacity awareness, individually reasonable requests can collectively exceed the resource limit... the failure mechanism being aggregate over-demand."*

But the resources they name are **compute budgets, bandwidth, memory, execution slots** — infrastructure. Mitigation offered is token/rate budgets. **Nobody has carried it to business resources**: customer attention, margin, refund authority. (Note: "Excessive agency" rose from 6th in 2025 to 3rd in 2026 on the OWASP list.)

### 6.5 Supporting evidence — marketing solved this 15 years ago
**Frequency capping.** From Braze's documentation:

> *"If three teams can schedule campaigns independently, the cap must sit above all of them. Otherwise each team will believe it is sending responsibly while the customer receives too many messages in total."*

That is the Commons thesis verbatim, written about marketing campaigns. Braze, Salesforce Marketing Cloud, Brevo and Netcore all ship platform-level frequency caps that sit above every campaign. Example from the literature: a contact in a nurture sequence + a product announcement + a re-engagement workflow can receive six emails in three days without any individual campaign doing anything wrong.

**Framing to use:** *"Agent platforms have the campaign problem and none of the campaign solutions. I'm porting a solved pattern from marketing automation into agent infrastructure."* This is far more defensible than "I found a flaw in Razorpay."

### 6.6 Supporting evidence — the gap is industry-wide, not Razorpay-specific
- **Mastercard Agent Pay**: Agentic Token from MDES *"scoped to a specific AI agent and a specific commerce policy"* — max spend per session, allowed merchants/categories, session lifetime. The cardholder *"enrolls an agent"* and grants **that agent** a policy. **Per-agent.** A cardholder with three enrolled agents has three independent ceilings and no aggregate ceiling.
- **Salesforce Agentforce**: Trust Layer, *"permission scopes that constrain what an agent could contact."* Per-agent.
- **Microsoft Copilot**: *"the integration user's permissions must be tightly scoped."* Per-agent.

---

## 7. What Commons Is

An **MCP-layer proxy** that sits between a fleet of agents and the MCP servers they call. It is *not* an MCP server — it speaks MCP on both faces: server to the agents, client to the real servers.

Two modes over **one rule engine**:
- **OBSERVE** — logs violations, allows everything through. Used in simulation.
- **ENFORCE** — blocks/defers violating calls. Used live.

The merchant writes rules **once**, in plain English. Same rules, same engine, same code path in both modes. The only difference is whether the world behind it is real and whether a violation is logged or stopped.

**Why the proxy position is the whole idea:** it is the one place every action from every agent must pass through. No agent source code needed, no agent modification, works identically for third-party agents you cannot inspect.

**Analogy for pitching:** air traffic control. Every pilot is competent and flying correctly. Without a tower, two competent pilots land on the same runway. The tower doesn't fly the planes — it sees the whole sky and occasionally says "hold."

**Name:** Commons (tragedy of the commons — independent actors over-consuming a shared finite resource none of them individually owns). Not locked; user hasn't confirmed.

---

## 8. Architecture

```
   WORLD SIMULATOR                      COMMONS PROXY
   (customers, clock,           +--------------------------+
    events)                     |  1. entity resolver      |
        |                       |  2. rule engine          |
        | emits events          |  3. decision + ledger    |
        v                       +--------------------------+
  +--------------+                   ^            |
  | Cart Recovery|-------------------+            | forwards
  | Subscription |-------------------+            | approved
  | Dispute Resp.|-------------------+            | calls only
  | RTO Shield   |-------------------+            |
  +--------------+                                v
   (LLM agents)                    +--------------------------+
                                   | Razorpay MCP (REAL, OSS) |--> Razorpay
                                   | Messaging MCP (ours)     |    TEST API
                                   +--------------------------+    (rzp_test_)
```

### 8.1 Components
1. **Commons proxy** (Python) — MCP server face + MCP client face, entity resolver, rule engine, decision ledger.
2. **World simulator** (Python) — stateful customer population, event clock, reactive personas.
3. **Agents** (Python, LLM-driven) — four, built to Razorpay's published job descriptions.
4. **MCP servers** — Razorpay's real OSS server + a messaging server we write.
5. **Dashboard** (Next.js) — see Section 13.

### 8.2 Using Razorpay's real MCP server
- Clone `razorpay/razorpay-mcp-server`, run locally with `rzp_test_` keys.
- Point Commons at it. Agents never talk to it directly.
- Approved calls hit Razorpay's genuine test API — real payment links, orders, refunds appear in the **Razorpay test dashboard**.
- **Best credibility shot in the video:** show real objects in Razorpay's own dashboard from run 1, then show the blocked ones absent in run 2. Proves it isn't mocked.

### 8.3 Why a second (and optionally third) MCP server is REQUIRED
1. **Razorpay's MCP has no messaging tools.** The most intuitive demo rule ("don't message a customer 3× a day") is unimplementable with Razorpay alone.
2. **Entity resolution only exists across servers — and it is the core technical contribution.** Inside Razorpay everything already carries `customer_id`; joining two Razorpay calls is trivial. The hard part is recognising `send_whatsapp(to: "+9198…")` and `create_payment_link(customer_id: 4471)` are the same human. With one server the novel part evaporates.
3. The "independently-built vendors" story needs more than one vendor.

**Minimum:** Razorpay's real server + one messaging server we write. Third (Shopify-shaped, orders/inventory) is nice-to-have.

---

## 9. The Rule Engine

Merchant writes rules in plain English; these compile to executable invariants. Demo rule set:

| Rule | Type |
|---|---|
| Max 1 outbound message per customer per 24h | frequency / cross-agent |
| Max 15% total discount per customer per 30 days | cumulative budget / cross-agent |
| Never send promotional offers to a customer with an open dispute | state-conditional / cross-agent |
| One agent per order at a time | mutual exclusion / cross-agent |

Decisions: `ALLOW` / `DEFER` / `BLOCK`, each with the rule that fired and the agents involved.

**Known risk:** natural-language → invariant compilation is itself LLM-generated and is a single point of failure. Mitigation: show the compiled invariant next to the English rule in the UI so the merchant can verify. Optional feature framing: surface ambiguous clauses back as "your policy is undecidable here." **If time is short, hardcode the invariants and treat NL authoring as a stretch goal.**

---

## 10. The World Simulator

Must be **dynamic, not static** (explicit user requirement).

- **Stateful customers** — persistent evolving state: subscription status, cart contents, dispute history, contact log, lifetime discount received. Agent actions mutate it.
- **Reactive personas** — LLM-driven customers that actually respond: irritation at the third message, accept/ignore a discount, escalate, opt out. Contact fatigue must produce *consequences*, not just a counter.
- **Event clock** — mandates lapse, carts get abandoned, disputes get filed over simulated time. Run 30 days in ~60 seconds.
- **Seeded and reproducible** — same seed = identical world. This makes the A/B comparison exact AND makes the free hosted demo possible (Section 15).
- **Knobs** — fleet size, customer overlap rate, dispute rate.

**Calibrate the generator to published numbers and cite them in the README:** UPI Autopay success 30–50%; Indian COD RTO rates; cart abandonment rates; dispute rates. A calibrated world is a very different conversation from an invented one.

---

## 11. Entity Resolution

The core engineering problem: recognising that tool calls from different agents to different MCP servers, naming things differently (`customer_id`, `contact`, `email`, phone number), refer to the same person.

**DECISION: declarative, not inferred.** The merchant declares mappings once per server (`WhatsApp.to` → phone → customer). Less magic, far more reliable in a demo, and the correct engineering choice. Inference was considered and rejected as demo risk.

*(This was the last open question posed to the user and never explicitly confirmed, but declared mapping was strongly recommended and no objection was raised.)*

---

## 12. The Agents

Four agents built to **Razorpay's own published job descriptions**: Cart Recovery, Subscription Recovery, Dispute Responder, RTO Shield.

**CRITICAL ANTI-CIRCULARITY RULE:** Do **not** design the agents to collide. Build them to do exactly what Razorpay says each agent does. If collisions emerge anyway, that is a genuine finding rather than a staged one. **State this explicitly in the README and the video.** This is the single most likely line of attack from a sharp judge.

---

## 13. Dashboard / UI Design

**Deployment:** standalone, NOT integrated into Razorpay's dashboard. Practical reason: no access. Better reason: embedding it inside Razorpay's UI would make it a Razorpay feature and destroy the cross-vendor thesis.

**Governing design principle:**
> Every existing dashboard is organised by agent. Commons is organised by customer.

Razorpay gives *"the agent's performance dashboard"* — singular, per agent. Braze organises by campaign. Agentforce by agent. If Commons ships another agent-centric list view, the idea becomes invisible. The information architecture must embody the inversion so the UI explains the thesis without a caption.

### 13.1 Hero screen — customer timeline
```
+--------------------------------------------------------------------+
|  Priya S.  ·  cust_4471  ·  +9198••••21        [4 violations]      |
|                                                                     |
|  Messages 4/1 per day !   Discount 23%/15% !   Dispute OPEN !       |
+--------------------------------------------------------------------+
|              Day 0        Day 1        Day 2        Day 3           |
|                                                                     |
| Cart Recovery --*=====================*--------------------         |
|                 whatsapp+10%          "5% more off"  !              |
|                                                                     |
| Subscription  -------*==================================            |
|                    whatsapp+8%  !                                   |
|                                                                     |
| Dispute Resp  ----------------*=========================            |
|                          contesting ₹3,400                          |
|                                                                     |
| RTO Shield    -----------------------------*============            |
|                                        flag prepaid-only !          |
|                                        ^ contradicts Cart Recovery  |
+--------------------------------------------------------------------+
```
Four lanes converging on one human; violations live *between* the lanes.

**Cheap high-value addition:** because runs are seeded, overlay run 2 on the same timeline with blocked actions as ghosted strikethroughs. Same world, damage removed, one image. Pure rendering, data already exists.

### 13.2 Other screens
- **Fleet overview** — exposure, not agent health. Customers ranked by accumulated exposure, violations by rule, total margin at risk. **Hosts the agent-count slider** (1 → 4 agents, violations climbing superlinearly). That chart is the thesis in one image; highest-value non-hero screen.
- **Rules** — plain-English rule, compiled invariant beside it, live per-rule compliance rate. Answers "you told your agents what to do — do they actually do it?" with a number.
- **Conflict ledger** — chronological `ALLOW`/`DEFER`/`BLOCK` with rule fired and agents involved; each row expands to full trace. This is the reproducibility promise made tangible.
- **Run comparison** — two runs side by side, same seed.
- **Connect** — one screen showing the one-line config change:
```diff
- "razorpay": { "url": "https://mcp.razorpay.com" }
+ "razorpay": { "url": "https://commons.yourapp.dev/mcp/razorpay" }
```

### 13.3 Design constraints
- **Design for the 5-minute video, not for a power user.** Large type, high contrast, visible motion. Counters should *tick up* live during simulation — more persuasive than any static chart. Legible at 1080p to a half-watching viewer.
- **Visible mode toggle** `OBSERVE > ENFORCE` in the header — proves one-engine-two-modes at a glance.
- **Aesthetic:** fintech infrastructure. Linear/Stripe/Vercel — restrained, monospaced numerals, dark-mode-first, red reserved exclusively for violations. **Avoid purple-gradient AI-product look**; audience is payments engineers.

### 13.4 Screen priority for 12 days
| Priority | Screens |
|---|---|
| **Must** | Customer timeline (hero), conflict ledger, simulation runner with A/B comparison |
| **Should** | Rules page with compliance rates, fleet overview with agent slider |
| **Cut** | Auth, multi-tenancy, settings, live-enforce polish, anything configurable that could be hardcoded |

---

## 14. Demo Script (5 minutes)

**Cast:** one merchant, four agents built to Razorpay's published specs, customer Priya (`cust_4471`, `+9198xxxxxx21`).

**1. Setup (30s)** — introduce merchant, four agents, the four stated rules.

**2. Run 1, OBSERVE mode (90s)** — simulated month plays out:
```
Day 0 09:00  Priya abandons ₹4,200 cart -> Cart Recovery
             -> send_whatsapp + create_payment_link(10% off)
             Commons: resolves phone -> cust_4471. 0 msgs today, 0% discount. ALLOW
             -> hits REAL Razorpay test API. Link appears in dashboard.

Day 0 09:40  UPI Autopay mandate fails -> Subscription Recovery
             -> send_whatsapp + retry offer 8% off
             Commons: 1 msg 40 min ago (different agent). 8+10 = 18% > 15%.
                      VIOLATION x2 — observe mode, passes through.

Day 1 11:00  Priya files a dispute -> Dispute Responder begins contesting

Day 2 10:00  Cart Recovery follow-up: "still interested? 5% more off"
             Commons: promotional contact to customer with OPEN DISPUTE.
                      Total discount now 23%. VIOLATION x2

Day 2 14:00  RTO Shield flags cust_4471 high-risk, wants prepaid-only
             Commons: DIRECT CONTRADICTION — Cart Recovery is incentivising
                      the customer RTO Shield is restricting.
```

**3. The reveal (30s) — THE MONEY SHOT** — cut to four per-agent dashboards, **all green**. Every action passed Razorpay's validation layer because every action was individually valid. *"Four clean dashboards. One customer being courted and sued in the same week, and 23% of margin gone."*

**4. Run 2, ENFORCE mode (60s)** — identical seed, agents, world. Second message deferred; discount capped at 15%; promo to disputing customer blocked; RTO Shield's restriction wins over Cart Recovery's incentive by declared priority. Show conflict ledger. Show Razorpay's dashboard with blocked objects **absent**.

**5. Generalise (45s)** — same engine, same proxy, different tools. Put the Mastercard three-token arithmetic on screen (3 agents × ₹50,000 session cap = ₹150,000 aggregate exposure nobody authorised). *"This isn't a payments problem."*

**6. Thesis (15s)** — the one-liner.

---

## 15. Deployment Strategy

**Vercel site = interactive demo. Actual tool = self-hosted via clone.**

### 15.1 Why self-hosted is CORRECT (not a budget compromise)
Commons is a proxy that sees every tool call — payment amounts, customer identifiers, refund decisions. A hosted version means routing a merchant's live payment traffic through a stranger's server. No merchant would accept that. Same call Langfuse, Arize Phoenix, promptfoo and agentgateway made. **Say this explicitly in the README** — it reads as judgment, not thrift.

### 15.2 The problem it creates
Nobody clones a repo from a cold email. Conversion to "actually saw the thing" ≈ zero if the link leads to a brochure plus install instructions. (Buildathon judges are different — they've committed to reading code.)

### 15.3 The fix — hosted interactive replay, zero backend
Runs are already deterministic and seeded. Export a complete run — every event, tool call, entity resolution, Commons decision — to JSON. Commit it. The Vercel site loads that JSON into **the same React components the local app uses.**

```
Local:   agents -> Commons -> MCP servers -> live state -> dashboard
Vercel:  run.json ---------------------------------------> dashboard
                     (same components, no backend)
```

Visitor gets: scrub Priya's timeline, click any decision for its trace, toggle OBSERVE/ENFORCE for ghosted blocked actions, drag the agent-count slider between pre-computed runs. **No API keys, no LLM calls, no infra cost.**

Label it honestly: *"replay of a recorded run — seed 4471, reproduce with `npm run demo -- --seed 4471`."* Converts skepticism into credibility.

**The determinism designed for A/B comparison is what makes the free hosted demo possible. That design decision pays for itself twice.**

### 15.4 Two-tier local setup — ceiling is ~60 seconds of friction
```bash
npx commons demo          # no keys. bundled fake Razorpay MCP.
                          # runs instantly, opens dashboard.

npx commons demo --real   # needs rzp_test_ + LLM API key.
                          # real Razorpay MCP, real test API.
```
Don't force the Razorpay signup on someone who's just curious. Tier 2 is what the video is recorded with.

### 15.5 Vercel site contents, in this order
1. **Thesis in two sentences, above the fold.**
2. **The interactive run, immediately** — not below three sections of feature copy.
3. **The agent-count slider chart.**
4. **Install command** for the minority who want to run it.

**For cold emails: deep-link straight into the timeline**, e.g. `commons.dev/replay?seed=4471&customer=4471`. They land inside the product with Priya's four violations on screen — no hero section, no scrolling, no decision.

### 15.6 README
Because selection is *"code evaluation only,"* the README **is** the pitch document. Open with the thesis and the timeline screenshot. Architecture second. Setup third. Do not bury the idea under prerequisites.

---

## 16. Zero-Budget LLM Strategy

### 16.1 The constraint (verified Aug 2026)
- **Groq free tier:** 30 RPM, 6,000 TPM, 14,400 req/day org-level. But good models are throttled harder — `llama-3.3-70b-versatile`: 30 RPM, **1,000 RPD, 12K TPM, 100K TPD**. `gpt-oss-120b`: 30 RPM, 1K RPD, 8K TPM, 200K TPD. **Limits are org-level; multiple API keys don't help.** OpenAI-compatible. No credit card.
- **Cerebras:** ~1M tokens/day on Llama 3.3 70B. Best token budget.
- **Google Gemini:** 10–15 RPM, frontier models, 1M context, no credit card.
- **OpenRouter:** ~30 free models, ~20 RPM **per model** (so spreadable).

**Naive math fails:** one invocation ≈ 3 calls × 4K tokens ≈ 12K tokens. Against Groq's 100K TPD that's **8 invocations/day**. Unusable.

### 16.2 Fix 1 — one provider per agent (also thematically correct)
| Agent | Provider |
|---|---|
| Cart Recovery | Groq |
| Subscription Recovery | Cerebras |
| Dispute Responder | Google Gemini |
| RTO Shield | OpenRouter |

Four separate budgets. And a heterogeneous fleet is *more* realistic than four agents on one model — real marketplaces won't be single-vendor. Strengthens the story while quadrupling budget.

### 16.3 Fix 2 — trim what you send
- **Don't expose all 15 Razorpay tools to every agent.** Cart Recovery needs `create_payment_link` + `send_whatsapp`. Two schemas, not fifteen: system prompt drops ~3K → ~600 tokens. (Pleasingly this is least privilege, the principle the project is built around.)
- **Compact state summaries**, not full customer JSON. ~40 tokens, not ~900.

Together: ~12K → ~3K tokens per invocation.

### 16.4 Fix 3 — cache on deterministic keys
Cache key = `hash(agent, event_type, relevant_state)`. With ~20 customers there are maybe ~30 distinct decision contexts; expect 70–80% hit rate. **Not cheating** — the agent genuinely made that decision once for that exact context; replaying it for an identical context is what determinism means. **Document this in the README.** Also makes dashboard iteration free.

### 16.5 Fix 4 — fewer customers, denser events
~20 customers sampled for **concurrent conditions**. Disclose precisely: *the customer population is sampled for overlap; the agents are not designed to collide.* Real merchants have thousands of customers of whom a fraction have concurrent conditions — this deliberately tests that tail.

### 16.6 Revised budget
```
20 customers x ~4 events    =  80 agent invocations
80 x ~3K tokens              = 240K tokens per full run
/ 4 providers                =  60K tokens each
```
Comfortably inside every free tier. Reruns near-free with caching. Video and Vercel replay run off committed trace JSON — **zero LLM calls**.

### 16.7 Tool-calling reliability risk
Weaker models call tools less reliably. Mitigations:
- Pick models with solid function-calling: Llama 3.3 70B, Qwen3, GPT-OSS 120B. Groq and OpenRouter are OpenAI-compatible so plumbing is standard.
- **Log malformed tool calls in a separate bucket from violations** so tool-call noise never pollutes the headline metric. Validate and retry on malformed.

### 16.8 Put this in the README (someone will ask "would this happen with a frontier model?")
> **Model quality is orthogonal to the finding.** The violations are structural. They occur because Cart Recovery cannot see Subscription Recovery — not because either agent reasoned poorly. A frontier model produces the same collision, because it has the same blind spot.

If credits ever materialise, one comparison run on a frontier model showing the violation persists would nail it shut. Worth doing, not worth blocking on.

### 16.9 Action item
Ask buildathon organisers whether participants get API credits. Razorpay built Agent Studio on Anthropic's Claude Agent SDK, so Anthropic credits are plausible. Costs one email.

---

## 17. Credibility Safeguards (anti-circularity)

These matter because the project is demonstrated on synthetic data. Every one was arrived at deliberately.

1. **The thing under test is NOT synthetic.**

| Real | Synthetic |
|---|---|
| The agents (actual LLM agents, real decisions) | The customer population |
| Razorpay's MCP server | The event timeline |
| Razorpay's test API | |
| The tool calls and their arguments | |

We simulate the *world*, not the *system under test*. A real agent deciding to send a third message is a genuine observation about genuine agent behaviour.

2. **The claim is logical, not statistical.** Not "your agents violate rules 14% of the time in production" but "given this sequence, this rule was breached and no per-agent control could have caught it." A unit test with fake inputs still proves a bug is real.

3. **Calibrate the world generator to published numbers and cite them.**

4. **Ship every violation with a full replayable trace.** Don't ask anyone to trust an aggregate. Show the sequence.

5. **Never design the agents to collide** (Section 12).

6. **State the limitation openly** rather than letting someone find it:
> *"This proves the failure mode exists and is undetectable by per-agent controls. It does not estimate how often it happens in production — that needs real merchant data, which is the natural next step."*

Naming your own limit reads as confidence.

---

## 18. Build Order

Recommended first step: **scaffold the proxy.** It's the smallest piece that makes the concept real and it de-risks the MCP plumbing before anything is built on top. Then rule engine + world simulator (everything hangs off those), then agents, then dashboard.

Rough sequencing for 12 days:
1. Proxy skeleton — MCP server face + client face, forwarding calls.
2. Entity resolver with declared mappings.
3. Rule engine + decision ledger (hardcoded invariants first).
4. World simulator with seeded determinism.
5. Four agents on four providers, with response caching.
6. Messaging MCP server.
7. Dashboard: timeline → ledger → runner.
8. Record run, export JSON, build Vercel replay.
9. Video + README.

---

## 19. Open Questions / Unresolved

1. **Name "Commons"** — proposed, not confirmed by user.
2. **Entity resolution: declared vs inferred** — declared strongly recommended; user never explicitly confirmed.
3. **NL policy authoring** — stretch goal; hardcode invariants if time is short.
4. **Third MCP server (Shopify-shaped)** — optional.
5. **Frequency of the failure mode in reality** — acknowledged weakness. For a small merchant, few customers have concurrent conditions. The strongest case is cross-vendor (Razorpay agents + Shopify agent + no-code merchant-built agent), not within Razorpay's own catalog, where they may coordinate internally without documenting it.
6. **Razorpay may absorb this as a feature** — real risk. Mitigated by the deliberately cross-platform framing.

---

## 20. Pitch Variants

**To Razorpay (Open Track, legible to Tracks 01/02):**
> Razorpay validates every action beautifully. Nobody validates the **sum** of them. Your guardrails are per-agent — correct today, and structurally insufficient the moment third-party builders publish to Agent Studio, because no single party can see the whole fleet.

**To Mastercard (uses their own product as the example):**
> A cardholder enrols three agents: shopping, travel, groceries. Each gets its own Agentic Token with its own session cap. Three agents × a ₹50,000 ceiling = ₹150,000 of exposure the cardholder never agreed to. Every token is correctly scoped. Nothing enforces the cardholder's total. Who owns the aggregate limit?

**General / any company running agents:**
> Every agent platform scopes permissions to the agent. None scope limits to the customer. Marketing automation hit this wall in 2010 and built global frequency caps above every campaign. Agent platforms have the campaign problem and none of the campaign solutions.

**Resume line:**
> An MCP-layer arbitration gateway that enforces policy on the entity being acted upon rather than the agent doing the acting — letting independently-built agents share customers and budgets without conflicting.

---

## 21. Key Sources

**Razorpay**
- Buildathon: https://razorpay.com/buildathon/
- Vulcan: https://razorpay.com/foundation-model/
- MCP server: https://github.com/razorpay/razorpay-mcp-server
- Agent Studio guardrails: https://razorpay.com/blog/razorpay-agent-studio-principles-guardrails-and-merchant-control/
- Agent Studio launch: https://razorpay.com/blog/agent-studio-ai-agents-by-razorpay/
- Agentic platform: https://razorpay.com/blog/razorpay-agentic-platform/
- Test/live modes: https://razorpay.com/docs/payments/dashboard/test-live-modes/

**Prior art / research**
- FraudBench: https://arxiv.org/abs/2608.18136
- GroundEval: https://arxiv.org/abs/2606.22737
- Adyen OPE for payments: https://arxiv.org/pdf/2501.10470
- Payment routing bandits: https://arxiv.org/abs/2308.01028
- Stakeholder-centric prompt injection: https://arxiv.org/html/2606.13385v1

**Landscape**
- Galileo Agent Control: https://galileo.ai/blog/announcing-agent-control
- Braze frequency capping: https://www.braze.com/docs/user_guide/engagement_tools/campaigns/building_campaigns/rate-limiting/
- Microsoft least privilege for agents: https://www.microsoft.com/en-us/security/blog/2026/07/16/least-privilege-for-ai-agents-identity-access-and-tool-binding/
- Mastercard agentic tokens: https://www.mastercard.com/global/en/news-and-trends/stories/2025/agentic-commerce-momentum.html
- Akamai agentic fraud: https://www.akamai.com/newsroom/press-release/akamai-research-commerce-becomes-the-epicenter-for-ai-bot-attacks-and-agentic-fraud-in-2026
- Agentic payment protocols compared: https://www.crossmint.com/learn/agentic-payments-protocols-compared

**Free LLM tiers**
- Groq free tier limits: https://tokenmix.ai/blog/groq-free-tier-limits-2026
- Free LLM APIs compared: https://openrouter.ai/blog/tutorials/free-llm-apis-compared/

---

## 22. Tone Guidance for the Pitch

- **Never frame this as "Razorpay made a mistake."** Per-agent scoping is correct, intentional, industry-standard least privilege. The framing is *"correct today, structurally insufficient at the marketplace step you've already announced."* Diplomatic AND accurate — and the user is trying to get hired by these people.
- **Lead with the ported-pattern framing** (marketing frequency capping), not with novelty claims.
- **Concede prior art openly.** FraudBench, GroundEval, MCP gateways, Galileo Agent Control all exist. The contribution is the entity-centric inversion, not the invention of agent governance.
