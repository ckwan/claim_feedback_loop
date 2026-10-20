# Why Day 2 and Day 3 are coded this way

This is a reference doc, not a build task — read it when you actually sit
down to do Day 2/3, or any time you want to understand the reasoning
behind human-in-the-loop agent code before you've written it.

Each section explains a design decision, why it matters specifically for
a *human-in-the-loop* system (not just "good practice" in the abstract),
and what breaks if you skip it.

---

## Day 2 — Wiring in a real LLM call + few-shot feedback

### 1. Why the LLM call lives in `services/suggestion_service.py`, not the router

The router's job is HTTP: parse the request, call something, shape the
response. The moment you put `client.messages.create(...)` inside a
FastAPI route handler, you've coupled "how do I generate a suggestion" to
"how do I handle an HTTP POST" — two things that change for completely
different reasons. You'll want to change your prompt weekly; you'll
almost never touch the route.

**What breaks if you skip this:** you can't unit test suggestion logic
without spinning up FastAPI's TestClient and mocking HTTP. You also can't
reuse the suggestion logic somewhere else (a batch job that re-scores
1,000 old claims overnight, say) without duplicating the route code.

### 2. Why `generate_suggestion(claim, db)` takes a `db` session even on Day 1

Day 1's stub doesn't touch the database at all — it's pure logic on the
`claim` object. So why accept `db`? Because Day 2 needs to *query* the
database (recent feedback, for few-shot context) from inside this same
function, and if the signature didn't already accept `db`, you'd have to
change every caller (the router) to pass it in — a second, unrelated
change bundled with "add the LLM call." Designing the seam before you
need it means Day 2's diff is contained entirely to the service file.

This is a general pattern: when you know a function is about to need a
new dependency, accept it (even unused) one commit before you need it,
so the "add the dependency" change and the "use the dependency" change
are separable and independently reviewable.

### 3. Why the LLM response gets validated with Pydantic before anything else touches it

An LLM's output is untrusted input — no different in kind from a value a
user typed into a form. It can be malformed JSON, missing a field, or
have a `confidence` of `1.7` instead of a number between 0 and 1. If you
skip validation and just do `response["action"]`, a bad response doesn't
fail loudly at the boundary — it fails three lines later with a
`KeyError`, or worse, it doesn't fail at all and a garbage suggestion
gets written to the database and shown to an adjuster.

The pattern: parse the raw LLM text → validate against a Pydantic model
→ only then let it flow into your domain code. If validation fails,
that's the one place you decide what happens next (retry, fallback,
raise) — not scattered `try/except` blocks downstream.

**Why this matters more for human-in-the-loop specifically:** a human is
about to read this output and act on it. A malformed suggestion that
silently becomes `None` for a field, or that never gets flagged, erodes
the one thing this system depends on — the adjuster's trust that a
suggestion is worth looking at.

### 4. Why "retry once, then fall back to the stub" instead of just raising an exception

Two different failure modes need two different responses:
- **Transient failure** (network blip, malformed JSON from a model that's
  usually fine) — worth one retry, because the cost of retrying is low
  and it often just works the second time.
- **Persistent failure** (model consistently returns something you can't
  parse, or the API is down) — retrying forever blocks the request and
  eventually times out anyway. Falling back to the deterministic stub
  logic means the *feature* (a claim gets a suggested next action) keeps
  working even when the *LLM* doesn't, just with lower quality and a
  `confidence: 0.0` that visibly signals "this wasn't a real model
  output."

This is a general resilience pattern (bounded retry + graceful
degradation) that matters more here than in most APIs, because the
alternative — a 500 error — means an adjuster's whole workflow stalls on
an LLM hiccup that has nothing to do with the claim in front of them.

### 5. Why few-shot context comes from a *database query*, not a static prompt

This is the actual "feedback loop" part of "human feedback loop" — the
mechanism has to be something that changes as more humans correct more
suggestions, otherwise it's not a loop, it's just a fixed prompt. Pulling
the 3 most recent overrides for similar claims (same org, same status)
means the prompt itself gets better over time without you touching code
or retraining anything — the *data* the prompt is built from evolves.

**Why scoped by org_id and status specifically:** an override on a
workers'-comp claim at $50k tells you very little about what a $2k
auto-injury claim should do next. Scoping the few-shot examples to
*similar* situations is what makes them useful signal instead of noise
diluting the prompt. This is also exactly the kind of tenant-isolation
detail (org_id) that a system-design interviewer is listening for — the
same discipline from Day 1's claims-listing query applies here too, just
one query deeper in the call stack where it's easier to forget.

**Why cap it at 3 examples:** unbounded few-shot context means your
prompt (and your bill, and your latency) grows without limit as more
feedback accumulates. Capping is a deliberate tradeoff — you lose some
signal from older corrections in exchange for a prompt that stays a
predictable size forever.

---

## Day 3 — Pagination bug-hunt + RAG history summary

### 6. Why the pagination prompt is deliberately underspecified

This isn't really about pagination — it's rehearsal for reading an AI
agent's diff critically instead of trusting it because it "looks done."
A vague prompt ("add sorting") gives the agent room to make an
assumption you didn't specify, and assumptions are exactly where bugs
hide. The specific bug this setup is designed to surface: does the new
sorted/paginated query *still* filter by `org_id`? It's very easy for an
agent (or a person) to rewrite a query for a new feature and accidentally
drop a `WHERE` clause that was "just sitting there" in the old version.

**Why this matters for human-in-the-loop systems specifically:** the
override-rate metric and the few-shot feedback query from Day 2 both
depend on org-scoped queries being correct. A silent tenant-isolation
bug here doesn't just leak data — it can leak *feedback* across
organizations, meaning Org A's adjusters' corrections start influencing
Org B's suggestions. That's a much worse failure mode than a typical
multi-tenant bug because it corrupts the learning signal, not just a
single read.

### 7. Why the RAG endpoint is explicitly marked as a simplified stand-in, with a comment explaining what "real" RAG would do

Two honest reasons: time, and getting the shape right before the scale.
Chunking, embedding, and vector search are worth building once you've
established that history_notes is a single small text field — building
an embedding pipeline for a field that's currently one paragraph is
solving a problem you don't have yet. The comment in the code isn't just
documentation — it's you demonstrating, to a reviewer or an interviewer,
that you know the difference between "stuffing everything into context"
(fine at this scale) and real retrieval (chunking, embeddings, top-k
similarity search — necessary once history_notes is actually a stack of
documents, visit notes, and records).

**Why this specific distinction matters for EvolutionIQ's second
problem:** "guidance based on claim history" implies *multiple*
documents per claim over time (visit notes, prior claims, medical
records) — not one text field. The moment that's true, "stuff it all in
the prompt" stops working (context limits, cost, and retrieval quality
all degrade), and you need actual chunking + embeddings + a vector store.
Marking the stub as a stand-in, with a one-line note on what changes at
scale, is the difference between "I built a toy" and "I built a
V0 of the right shape."

### 8. Why the tests target the service layer, not just the HTTP endpoints

A test that goes through `TestClient.post(...)` is testing the whole
stack — FastAPI routing, dependency injection, the database, *and* your
logic — all at once. When it fails, you don't immediately know which
layer broke. A test that calls `generate_suggestion(claim, db)` directly
is testing one thing: does this function do the right thing given this
input. That's only possible because Day 1 already separated the service
from the router — this is the payoff of that decision showing up two
days later.

**Why this matters more once an LLM is involved:** LLM calls are slow,
cost money, and are non-deterministic — you don't want a full HTTP
integration test hitting a real model on every CI run. Testing the
service layer means you can mock just the LLM client (one boundary) and
test everything else (prompt construction, few-shot querying, validation,
fallback logic) fast, deterministically, and for free.

---

## The throughline

Every one of these choices is the same underlying instinct applied at a
different layer: **draw a boundary around the part that's uncertain,
untrusted, or slow (the LLM), and make everything on the other side of
that boundary simple, typed, and testable.** Router calls service.
Service calls agent/LLM client. LLM output gets validated before it's
trusted. Tenant scoping gets enforced at every query, especially the ones
that feed the feedback loop itself. That's not a FastAPI pattern or an
AI pattern specifically — it's just where the discipline has to live
once part of your system stops being deterministic.
