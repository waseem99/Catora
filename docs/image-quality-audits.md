# Deterministic image and alt-text audits

Catora adds an immutable `builtin.<category>.image_quality` rule version for every immutable taxonomy category. The rule operates on a synthetic canonical `images` attribute assembled from normalized `ProductImage` rows, so no schema migration or external image analysis service is required.

The versioned `image-quality-v1` checks:

- at least one image exists;
- every image has non-empty alt text;
- alt text is between 5 and 300 normalized characters;
- alt text is not composed only of generic terms such as “image”, “photo” or “product”;
- alt text does not exactly duplicate the normalized product title;
- image checksums or URLs are not duplicated within the product inventory.

A failed rule contributes to discoverability readiness and creates one deterministic product-level finding with the complete sorted failure-code set. The remediation type is `improve_image_metadata` and the business-impact category is `discoverability`.

Image URL, alt text, position, variant scope and checksum are included in the existing product snapshot serialization. Any inventory or alt-text change therefore updates the product snapshot hash and is selected by incremental auditing. Matching product-level provenance records are attached as finding evidence when available.

The rule does not fetch image bytes, infer visual content or call an LLM. Resolution dimensions, visual similarity and accessibility quality beyond deterministic text checks remain separate future rule versions.
