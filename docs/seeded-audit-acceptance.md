# Seeded audit acceptance fixture

The deterministic audit suite includes a fixed 100-product catalog with UUIDv5 product identities and one immutable high-severity width rule. The fixture intentionally contains 20 missing width values and 80 valid canonical values.

A baseline run therefore produces:

- 180 evaluated contributions: one presence contribution for every product and one validation contribution for each of the 80 present values;
- 20 reproducible findings;
- 10,800 eligible and evaluated weight;
- 9,600 passed weight;
- an overall score of 8,889 basis points;
- 10,000 basis points of confidence.

The fixture is evaluated twice and requires byte-for-byte-equivalent evaluation objects, finding fingerprints, score contributions, and score totals.

A second scenario updates a deterministic ten-product slice. Two missing widths become valid, while the other eight selected products remain valid. The incremental contribution merge must exactly equal a full rerun over all 100 updated products. Both paths produce 182 contributions, 18 findings, 10,920 evaluated weight, 9,840 passed weight, and a score of 9,011 basis points.

This fixture protects the Issue #8 acceptance requirements for repeatability, fixed totals, and incremental-versus-full score and finding parity without depending on an LLM, wall-clock time, random UUID generation, or unordered database results.
