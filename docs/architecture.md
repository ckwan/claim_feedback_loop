# Architecture details

Deeper flow diagrams for the claims feedback loop. The overview is in the
[README](../README.md).

## Generating a suggestion

The LLM is never trusted directly. Output is validated, retried once, then
replaced by a rule-based fallback.

```mermaid
flowchart TD
    A["POST /claims/id/suggest"] --> B["load claim<br/>(scoped by org)"]
    B --> C["build prompt:<br/>claim + recent overrides<br/>as few-shot examples"]
    C --> D["call LLM"]
    D --> E{"valid against<br/>strict schema?"}
    E -->|yes| G["save suggestion"]
    E -->|no| F{"already retried?"}
    F -->|no| D
    F -->|yes| H["rule-based fallback"]
    H --> G
```

## Recording the adjuster's decision

```mermaid
flowchart TD
    A["POST /suggestions/id/feedback"] --> B{"suggestion stale?"}
    B -->|yes| N409["409: request a new suggestion"]
    B -->|no| C{"action"}
    C -->|accepted| D["save feedback"]
    C -->|overridden| E{"override_reason given?"}
    E -->|no| N422["422"]
    E -->|yes| F["save feedback with reason"]
    D --> G["write audit event"]
    F --> G
    F -.->|"used as few-shot example"| H["next suggestion for this org"]
```

## Hybrid search

Tenant filtering happens inside the SQL, not after the fact.

```mermaid
flowchart LR
    Q["query"] --> E["embed query"]
    E --> V["vector search<br/>(HNSW)"]
    Q --> K["keyword search<br/>(full text GIN)"]
    V --> F["merge with<br/>Reciprocal Rank Fusion"]
    K --> F
    F --> R{"rerank on?"}
    R -->|yes| L["LLM rerank<br/>(validated, falls back<br/>to original order)"]
    R -->|no| O["results"]
    L --> O
```

## Claim lifecycle

Editing is allowed while a claim is open or under review.

```mermaid
stateDiagram-v2
    [*] --> open: claim created
    open --> under_review: start review
    under_review --> approved: approve (final)
    under_review --> denied: deny (final)
    approved --> [*]
    denied --> [*]
    note right of open
        Edit details allowed in open and under_review.
        Editing the amount or notes makes earlier
        AI suggestions stale.
    end note
```

## Editing a claim

Editing the amount or notes makes earlier AI suggestions stale, so an adjuster
can't act on advice that no longer matches the claim.

```mermaid
flowchart TD
    A["PATCH /claims/id<br/>amount, claimant_name, history_notes"] --> B{"claim in this org?"}
    B -->|no| N404["404 (same as missing)"]
    B -->|yes| C{"approved or denied?"}
    C -->|yes| N409["409 final, no edit"]
    C -->|no| D{"valid?<br/>amount above 0, name not blank,<br/>notes under 5000, no extra fields"}
    D -->|no| N422["422"]
    D -->|yes| E{"any value different?"}
    E -->|no| NOOP["200, nothing written"]
    E -->|yes| F["write one history row per changed field"]
    F --> G{"amount or notes changed?"}
    G -->|yes| H["mark claim's suggestions stale<br/>and log it in the history"]
    G -->|no| I["commit"]
    H --> I
    I --> J{"notes changed?"}
    J -->|yes| K["re-index claim for search<br/>(never fails the edit)"]
    J -->|no| L["200 updated claim"]
    K --> L
    L -.-> M["accept or override of a stale suggestion<br/>returns 409: request a new suggestion"]
```

## Idempotent intake

```mermaid
flowchart TD
    A["POST /claims<br/>external_ref present"] --> B{"org_id in body equals X-Org-Id?"}
    B -->|no| N403["403"]
    B -->|yes| C{"claim with same<br/>org_id and external_ref?"}
    C -->|yes| R200["200 existing claim, unchanged<br/>nothing written<br/>(warn if payload differed)"]
    C -->|no| D["INSERT claim and history row"]
    D --> E{"unique index<br/>(org_id, external_ref) violated?"}
    E -->|"yes: a concurrent retry won"| F["roll back, re-read"]
    F --> R200
    E -->|no| R201["201 new claim, then index notes"]
```
