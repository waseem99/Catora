# Enrichment policy enforcement

Workspace enrichment policy is applied at every generation boundary.

- Synchronous generation resolves policy before target validation or provider execution.
- Queued generation stores the effective controls and budget in the job snapshot.
- Worker execution resolves policy again, so later tightening is honored.
- Request controls can add restrictions, but cannot remove workspace restrictions.
- The effective budget is the lowest applicable request, system, and workspace ceiling.
- Prompt construction and persistence use the effective request.

This slice does not change provider selection or add frontend behavior.
