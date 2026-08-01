# Local profile and Google Business Profile intelligence

Catora stores provider-neutral, append-only local-profile observations and compares them with the
approved restaurant location evidence from the restaurant domain. It does not create, verify,
transfer, suspend, appeal, edit, or delete a production profile.

## Capability discovery

Every provider account records an operation-level capability matrix with one of these states:

- `documented`: the operation is documented by the provider but not granted or tested;
- `granted`: the account appears to have the required scope or permission;
- `tested`: the operation passed an account-level acceptance test at a recorded time;
- `unavailable`: the operation is not available for the account/runtime;
- `prohibited`: Catora policy forbids the operation.

Mutation capabilities cannot be presented as available in `local-profile-intelligence/v1`. The
initial Google Business Profile adapter therefore fails explicitly until official capability
discovery, OAuth review, account access, quota review, and a real acceptance record exist. A
synthetic provider supports deterministic repository and CI validation without pretending a live
Google account is connected.

## Observations

A profile observation can contain only approved public listing facts:

- provider profile identity and state;
- title, public phone, public address, coordinates, website, menu and ordering URLs;
- regular and special hours;
- categories, attributes, service areas and a media count;
- observation time, provider update time and deterministic observation hash.

Each changed observation is append-only. Repeating the same profile/hash is idempotent. A newer
observation retires the prior current projection but preserves history.

## Identity and completeness

Branch/profile matching is deterministic and conservative:

- exact name + phone + address;
- approved alias + phone + address;
- bounded combinations of name/alias, address, phone and website host.

Equal best candidates are `ambiguous` and require a human decision. An unsupported profile is
`unmatched`; Catora never forces it onto a branch.

Completeness reports the exact present and missing fields across title, address, phone, categories,
hours, website, menu URL, ordering URL, service areas, media and attributes. Missing provider
capabilities are not rendered as false zeros.

## Conflicts

The first version detects evidence-backed differences in name, public phone, public address and
website. Every conflict retains both normalized values, the profile observation, linked restaurant
location, severity, first/last seen times and deterministic fingerprint. Future category, hours,
service-area and URL-policy rules use the same append-only lifecycle.

## Security and disconnect

- OAuth/access tokens are referenced through managed credentials and never stored in observations,
  UI payloads, logs, prompts or exports.
- Accounts, profiles, links and conflicts are workspace scoped.
- Sync is read-only, rate limited by the future accepted provider adapter, and independent from
  restaurant ordering.
- Disconnect revokes the credential reference, stops sync, marks current observations inactive and
  retains bounded evidence and audit history.

Ranchers account discovery and any production profile activity remain gated by issue #222.
