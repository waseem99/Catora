# Governed restaurant reviews and reputation intelligence

Catora imports approved public review observations, preserves update/deletion history, derives
evidence-backed themes and risks, and creates human-reviewable response drafts. It does not post,
delete, gate, incentivize, fabricate, or selectively solicit reviews.

## Evidence lifecycle

Each observation records provider/account identity, public review ID, branch identity, rating, text,
language, public response state, provider timestamps, observation time, and a deterministic hash.
Repeated hashes are idempotent. Updated reviews retire the prior current projection; deleted or
unavailable states are explicit and historical evidence remains append-only.

## Analysis and escalation

`reputation-rules/v1` uses transparent phrase rules to classify food quality, service, delivery,
cleanliness, value, and order accuracy. Food-safety, allergen, threat, legal, discrimination, and
similar high-risk signals require human escalation. Missing text is never invented, and a low rating
without text remains an explicit unsupported reason.

## Response drafts

A draft is generated only from the persisted review text, approved restaurant name, and a versioned
response policy. Every draft stores the source review hash and requires a human decision. The
contract prohibits posting; no provider mutation route or provider adapter is included. Escalated
reviews cannot receive an automatic draft.

## Privacy and safety

Reviewer display names are treated as bounded public evidence and are never joined to customers,
orders, payments, loyalty accounts, addresses, or internal profiles. No deanonymization, review
gating, mass response, sentiment manipulation, ranking promise, or commercial guarantee is
permitted.

The runtime supports synthetic acceptance only until each review provider's terms, scopes, quotas,
account access, deletion behavior, and response capabilities are explicitly accepted. Ranchers
reviews remain gated by issue #222.
