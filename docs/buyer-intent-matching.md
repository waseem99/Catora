# Deterministic buyer-intent matching

The buyer-intent matcher accepts a validated structured intent and canonical product facts.
It does not call an LLM and does not use vector similarity as the final eligibility decision.

Hard constraints produce one of four product states:

- `confident_match`: every hard constraint is supported by canonical data and source evidence;
- `possible_match_missing_data`: no known violation exists, but required data, evidence or a
  comparable unit is missing or conflicting;
- `non_match`: a known category or hard-constraint value violates the intent;
- `insufficient_category_data`: the intent requires a category but the product is not mapped.

Numeric comparisons use deterministic conversions for supported length and mass units. Unknown,
incompatible or one-sided units fail closed as conflicting data. Soft preferences produce a
separate weighted score in basis points and never override hard-constraint status.

The first slice evaluates one product or variant candidate at a time. Persistence, intent editing,
run orchestration, coverage aggregation and natural-language parsing are separate Issue #10 slices.
