# Security policy

## Supported code

Security fixes are applied to the current `main` branch and to the newest installable integration artifacts produced from it. Historical branches, superseded pull requests, and expired workflow artifacts are not supported release channels.

## Reporting a vulnerability

Do not include secrets, credentials, customer data, private URLs, or exploit details in a public issue.

Use GitHub's private vulnerability reporting or security-advisory flow for this repository when it is available. If private reporting is unavailable, open a minimal public issue that contains no sensitive details and asks the repository owner representative to establish a private channel.

Include the affected component, version or commit, reproduction conditions, expected impact, and any safe mitigation already identified.

## Authorized triage representative

The repository owner and CODEOWNER, `@waseem99`, is the authorized repository-side representative for security triage, patch approval, release decisions, and coordinated disclosure. Repository authority is documented in [`docs/governance/repository-ownership.md`](docs/governance/repository-ownership.md).

## Scope

This policy covers the Catora API, web application, background workers, Shopify integration, WordPress Service Visibility bridge, catalog bridges, build workflows, and release artifacts stored in this repository.

Client systems, third-party platforms, domains, stores, and hosting accounts remain subject to their own owner authorization and incident processes.
