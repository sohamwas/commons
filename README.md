# Commons

An arbitration layer for merchants running more than one AI agent.

Every agent platform scopes permissions to the **agent**. None scope limits to the
**customer**. So each agent can be individually correct while the merchant is
collectively wrong: cart recovery offers 10%, the loyalty agent offers another 10%, and
nobody exceeded their own ceiling.

Commons sits between your agents and the vendor MCP servers they call. It resolves every
call to the person being acted upon, keeps a ledger across all agents and all vendors, and
applies limits to that person rather than to whoever happened to call.

It runs entirely on your machine. It sees payment amounts, customer identifiers and refund
decisions, so it is never hosted for you.

---

## Getting started

Three ways in. The launcher is the shortest; Docker if you would rather it were
containerised; the manual path below if you want to see what either of them is doing.

### One command

```bash
python scripts/start.py
```

That is the whole thing from a clean clone. It creates the virtualenv, installs both sets
of dependencies, starts the gateway, the dashboard and the reference messaging vendor,
waits until each is answering, and prints where to look. Ctrl+C stops all of them.

Needs Python 3.11+ and Node 20+, which the gateway and the dashboard already require. It
is stdlib only, because a launcher whose job is to install the dependencies cannot have
dependencies of its own.

```bash
python scripts/start.py --mode ENFORCE     # start enforcing straight away
python scripts/start.py --no-messaging     # skip the local reference vendor
python scripts/start.py --gateway-port 9000 --dashboard-port 4000
```

First run installs npm packages and takes a few minutes. After that the gateway answers in
seconds and the dashboard in under a minute.

### Docker

Same three services, same three ports, if you would rather not have Node and Python on the
host. On Windows this needs the WSL2 backend, which is a reboot and a 1GB install before
you see anything; the launcher above needs neither.

```bash
cp .env.example .env      # optional: add Razorpay test keys now or from Connect later
docker compose up
```

Dashboard on <http://localhost:3300>, gateway on <http://localhost:8787>. It starts in
OBSERVE, which blocks nothing.

Three services come up: the gateway, the dashboard, and the reference messaging vendor
that exists to show Commons resolving one customer across two independently built
vendors. Razorpay and Resend are not among them, because they are remote MCP servers
reached over HTTPS and configured at runtime rather than baked into an image.

Every port is published to `127.0.0.1`, not `0.0.0.0`. Commons sees payment amounts,
customer identifiers and refund decisions, so containerising it must not quietly widen
who can reach it.

`commons.db`, `agents.yaml` and `vendors.yaml` live on a named volume, so they survive a
rebuild. To start genuinely clean:

```bash
docker compose down -v
```

Two things differ from the manual setup. Add the local messaging vendor as
`http://messaging:8788/mcp`, not `127.0.0.1`, because inside the gateway container
loopback is the gateway itself. And point your agents at
`http://127.0.0.1:8787/mcp/<agent>/<vendor>` exactly as below: the published port makes
the container indistinguishable from a local process.

### 1. Install

```bash
python -m venv .venv
.venv/Scripts/pip install -e .          # Linux/macOS: .venv/bin/pip
cp .env.example .env
```

Put your Razorpay **test** keys in `.env`. Commons refuses to start against a live key,
because it forwards real write calls.

### 2. Start the gateway

```bash
.venv/Scripts/python.exe scripts/run_proxy.py
```

It starts in OBSERVE, which records decisions and blocks nothing. A vendor that is not
reachable is reported rather than fatal, so you can start with one and add more later.

### 3. Start the dashboard

```bash
cd dashboard && npm install && npm run dev
```

Open <http://localhost:3300>.

### 4. Add your vendors

On **Connect**, add each MCP server your agents call. Either a URL, or a command to run
for the many MCP servers distributed as something you launch:

```
url:     https://mcp.example.com/mcp
command: npx    args: -y @modelcontextprotocol/server-everything
```

A secret is written as `env:MY_TOKEN` and read from `.env` at connect time, so it never
lands in the file.

Razorpay is added for you if its keys are in `.env`.

A vendor also needs a **semantics manifest** for Commons to govern it. Without one its
calls are forwarded and logged, but no rule can reach them, and Connect says so per
vendor. Manifests live in `commons/semantics/manifests/`.

### 5. Register your agents

Still on **Connect**: give the agent an id and press Add. By default it gets **every tool
those vendors publish**, which is what it has today without Commons, and every call is
still governed. The rules are about what happens to a customer, not about which tool did
it.

That is all it needs — no prompt, no model, no source. It is served immediately, with no
restart.

Narrowing an allowlist is a real second layer, and a better decision to make with
evidence than at onboarding. Once the agent has run, Connect shows what it actually
called — `used 3 of 42 tools` — with one click to narrow it to those. You can also tick
tools upfront if you already know.

Then replace the vendor URL in that agent's MCP config with the one Connect shows you:

```diff
- "razorpay": { "url": "https://mcp.razorpay.com/mcp" }
+ "razorpay": { "url": "http://127.0.0.1:8787/mcp/cart-recovery/razorpay" }
```

That is the whole integration. Nothing inside the agent changes, which is why it works for
agents you did not write and cannot modify.

### 6. Tell Commons who your customers are

Commons unifies `+91 98000 00021`, `9800000021` and `09800000021` on its own — one detail
written three ways. It will **not** guess that a phone number and an email belong to the
same person. In a system that can block a payment, a wrong merge is worse than no merge,
so you state it once.

On **Data**, either sync from Razorpay (same keys, nothing to export) or import a CSV.
`examples/sample-customers.csv` shows the shape; real export headers like `Customer ID` and
`Mobile Number` are understood, and any column it does not recognise is named rather than
silently dropped.

### 7. Watch, then enforce

Leave it in OBSERVE for a few days. Nothing is blocked, so no agent can break.

Work through **Review**: for each flagged call, say whether it should have been stopped. A
rule you keep marking wrong is a rule that needs changing, not agents that do — edit it on
**Rules**, where the limits are yours to set.

When you are convinced, switch to **ENFORCE** from the header. Violating calls are then
stopped before they reach the vendor, and the agent receives an ordinary MCP tool error.

---

## What it enforces

Five primitives, each about **accumulation on one customer**. None can be checked from a
single call in isolation, which is exactly why per-agent validation cannot express them.

| Rule | Question it answers |
|---|---|
| `RateLimit` | How many times has this happened to them in a window? |
| `CumulativeBudget` | How much have they been given in total? |
| `StateCondition` | Is this allowed given their current state? |
| `MutualExclusion` | Is another agent already working this order? |
| `Contradiction` | Does this undo what another agent just did? |

The last one is the interesting one. A fulfilment restriction and a discount incentive on
the same customer is not a limit breach — nobody exceeded anything. It is the merchant
working against itself, and no per-agent control can see it.

Limits are editable on **Rules** and take effect on the next call. Your agents stay
connected.

---

## How it knows what a call means

A **semantics manifest** maps each vendor tool to what it does and to whom:

```yaml
create_payment_link:
  action_class: discount_grant
  entity:    { from: args, path: customer_contact, as: phone }
  magnitude: { from: args, path: notes.discount_pct, unit: percent }
  resource:  { from: args, path: [notes.order_id, notes.subscription_id] }
```

These are written from the vendor's **published tool schemas**, not from its source. That
is what lets Commons govern a third-party agent calling a third-party vendor. Manifests
live in `commons/semantics/manifests/`; a new vendor needs one.

---

## Layout

```
commons/proxy/       the gateway: routing, the decision path, the agent registry
commons/rules/       the five primitives and the policy engine
commons/ledger/      SQLite: every call, every decision, every review
commons/identity/    entity resolution and customer import
commons/semantics/   what each vendor tool means
dashboard/           the local dashboard (Next.js)
mcp_servers/         a reference messaging vendor, and an in-memory one for tests
examples/            a worked agent that imports nothing from commons/
scripts/             start (the one-command launcher), run_proxy, the stress harness
Dockerfile           the gateway and the messaging vendor, one image, two commands
dashboard/Dockerfile the dashboard: built to static HTML, served by nginx
docker-compose.yml   all three, ports bound to loopback
```

`agents.yaml`, `vendors.yaml` and `commons.db` are created on first run. They are
yours; none are committed.

---

## Testing

```bash
.venv/Scripts/python.exe -m pytest tests/ -q
.venv/Scripts/python.exe scripts/stress_commons.py
```

The stress harness runs a second gateway on its own port and database with in-memory
vendors, so it never touches your data or your Razorpay account. It covers load,
concurrent grants against one cap, edge cases, enforcement, and latency.

Two bugs worth knowing about, because both are the kind that only appear under real use:

- A call the vendor **rejected** used to consume the customer's budget, so a payment link
  that failed still spent their discount.
- **Concurrent** grants each read the ledger before any of them had written, so three
  agents could pass a cap that only one of them fit under. Commons now reserves at
  decision time.

---

## Limits worth knowing

- **A new vendor needs a manifest.** Config alone is not enough; an ungoverned tool is
  forwarded and logged loudly, not silently allowed.
- **Review verdicts are advisory.** They tell you a rule is misfiring; they do not disable
  it. A rule that switches itself off is not something you want in a payment path.
- **Managed agent platforms cannot be routed through Commons** if they do not let you
  change where an agent sends its tool calls. That is the gap this exists to describe.
