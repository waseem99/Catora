# Deterministic duplicate-content audits

Catora creates one immutable `builtin.<category>.duplicate_content` rule per immutable taxonomy category. The `duplicate-content-v1` algorithm compares active products only within the same category, reducing false positives across materially different product types.

Exact matches use normalized title and description signatures. Conservative near matches use a deterministic 64-bit SimHash candidate index split into four 16-bit bands, followed by a Hamming-distance limit of three and token-Jaccard verification. Titles require at least 16 normalized characters and four unique tokens; descriptions require at least 80 characters and twelve unique tokens. Exact groups do not expand every peer pair, and finding payloads retain at most twenty deterministic peer samples while preserving full per-code match counts.

A matched product receives one stable `duplicate_content` finding with explicit exact or near title/description failure codes, `discoverability` business impact and `differentiate_product_content` remediation. Title and description evidence is attached when available. The score contribution belongs to discoverability readiness.

Duplicate membership is a catalog-level dependency: changing or deleting one product can change findings for another product. Therefore, after duplicate rules are introduced, a non-empty incremental run expands to the full current catalog plus deleted baseline product identifiers. This preserves exact full-versus-incremental score and lifecycle parity; a no-change incremental run still reuses its baseline without reevaluation.

The algorithm does not use embeddings, LLMs or remote services. It intentionally favors transparent conservative matches over broad semantic similarity. Cross-category comparisons, multilingual semantic equivalence and image-based product identity remain separate future rule versions.
