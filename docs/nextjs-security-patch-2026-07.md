# Next.js July 2026 security patch

The hosted demo deployment upgrades both `next` and `eslint-config-next` from `16.2.10` to
`16.2.11` and commits the regenerated npm lockfile.

The upgrade follows the Next.js July 2026 security release for the active 16.2 LTS line. It is a
patch-level dependency change and does not change Catora application behavior or architecture.

The repository security job remains authoritative and must pass `npm audit --audit-level=moderate`
alongside the complete lint, type-check, test and production-build pipeline.
