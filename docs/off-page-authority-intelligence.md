# Off-page authority intelligence

Catora stores provider-neutral, dated authority observations and turns eligible evidence into human-reviewed opportunities. The module defaults off through `CATORA_AUTHORITY_INTELLIGENCE_ENABLED=false`.

The repository runtime supports deterministic synthetic acceptance only. Backlink, citation, mention and permitted-public-web providers remain unavailable until their terms, access, quota, legal basis and account-level acceptance are verified.

## Allowed observations

An observation may describe a public backlink, local citation, unlinked mention or media opportunity. It records:

- the approved provider account and external observation identity;
- source and target URLs;
- public source title and anchor or mention text;
- an exact, alias, ambiguous or unmatched restaurant identity state;
- current, new, lost, broken or not-applicable link state;
- nofollow and sponsored indicators;
- dated provider metrics, observation time and deterministic hash.

Provider metrics cannot contain user, customer, order, transaction, email, phone, IP or session identifiers. Catora does not scrape private pages, bypass access controls, or infer a restaurant identity when evidence is ambiguous.

## Prohibited practices

Catora rejects or suppresses observations and opportunities involving:

- paid links or backlink purchases;
- link farms or private blog networks;
- guaranteed ranking or traffic claims;
- automated mass outreach;
- fake citations, fabricated relationships or deceptive placement;
- activity outside provider terms or the approved public-web scope.

The module does not assign a monetary value to links and does not guarantee ranking, citation, traffic, revenue or ROI.

## Opportunities

Eligible observations can produce deterministic, evidence-backed opportunities such as citation correction, link reclamation, relationship outreach, expert commentary, a data story, community partnership or an approved guest contribution.

Every opportunity contains a risk state, rationale, verification method, owner role, evidence hashes, transparent score and version. Ambiguous or unmatched identity produces a suppressed zero-score item, not an actionable recommendation.

## Suppression and outreach drafts

A workspace may record do-not-contact, legal, provider-terms, brand-policy or prior-opt-out suppressions. Active suppression blocks draft creation.

An outreach draft requires:

- a non-prohibited, non-suppressed opportunity;
- evidence hashes for every factual claim;
- a completed suppression check;
- a confirmed legal basis;
- an authenticated human author and reviewer.

Drafts can be approved or rejected, but Catora exposes no sending or publishing route. `send_allowed` is permanently false in the contract. Any external contact is performed manually in an approved system outside Catora.

## Credentials and disconnect

Only managed references using `env:`, `vault:`, `secret:` or `synthetic:` are accepted. Raw tokens are rejected. Disconnect revokes the credential reference and stops new observations while retaining bounded evidence, decisions and audit history.

No Ranchers account, backlink provider, citation provider, mention provider or outreach mailbox is connected by this repository implementation. Ranchers activation remains gated by issue #222 and explicit external acceptance.
