# Hilarious live acceptance

This runbook finishes the live acceptance of Catora's WordPress Service Visibility closed loop on `hilariousai.io`. Repository-side monitoring, human-approved draft delivery, credential rotation, and Google measurement support are already implemented; this runbook covers the remaining external production actions and evidence.

## Preconditions

- Catora API, worker, and web production deployments are healthy.
- The existing Hilarious WordPress source is healthy before changes begin.
- Use the validated WordPress Service Visibility `0.2.3` artifact from workflow run `31246463699` / artifact `9018648872`.
- Artifact wrapper SHA-256: `9fc66ff77d9bf39b18585dbc93a78a0b5081048058a87f270cf435c6ded6bdbb`.
- Installable inner ZIP SHA-256: `8c1ce0b9aac8d82618d0aa7bd84b12f403c2b154d8181d34441a507f18ed85eb`.
- Never record WordPress credentials, rotated tokens, Google service-account JSON, or other secrets in GitHub.

## Acceptance sequence

1. **Upgrade WordPress bridge**
   - Install/upgrade to plugin `0.2.3`.
   - Confirm the existing connection remains Healthy.
   - Run one manual snapshot and reconcile the accepted public-page count.

2. **Enable production feature gates**
   - Confirm `CATORA_SERVICE_VISIBILITY_ENABLED=true` remains enabled.
   - Set `CATORA_SERVICE_VISIBILITY_DRAFTS_ENABLED=true`.
   - Set `CATORA_SERVICE_VISIBILITY_MONITORING_ENABLED=true`.
   - Set `CATORA_MEASUREMENT_CONNECTORS_ENABLED=true`.
   - In WordPress, explicitly enable Scheduled Snapshots and Approved Drafts.

3. **Rotate the WordPress bridge credential**
   - Rotate the existing Hilarious source credential in Catora.
   - Replace the credential privately in WordPress.
   - Prove the old credential fails closed.
   - Prove the new credential succeeds with a fresh snapshot.

4. **Prove automatic change detection**
   - Record the current Catora report/finding state for one low-risk public page.
   - Make and publish a small controlled visible change in WordPress.
   - Confirm plugin `0.2.3` queues the bounded post-save verification snapshot.
   - Confirm Catora records the page as changed and updates the finding lifecycle correctly.

5. **Prove human-approved remediation**
   - Select one evidence-backed, low-risk WordPress finding in `Review fixes`.
   - Prepare/edit the proposed content or metadata change.
   - Explicitly approve it.
   - Confirm WordPress creates an unpublished draft and the live page is unchanged.
   - Confirm stale-revision protection fails closed if the source page changed meanwhile.
   - Manually publish the accepted draft as an authorized WordPress user.
   - Confirm the subsequent Catora verification scan records the expected improvement or resolution.

6. **Connect Search Console and GA4**
   - Store a dedicated Google service-account JSON only in a Railway-managed environment variable.
   - Grant that service account read-only access to the exact Hilarious Search Console and GA4 properties.
   - Enter only the exact Search Console property identifier and GA4 numeric property ID in Catora.
   - Run a manual sync and verify aggregate observations are stored.
   - Verify the daily background sync runs against the connected accounts.

7. **Upgrade PHP**
   - Upgrade the Hilarious runtime from PHP `7.4.33` to PHP `8.3+`.
   - Re-run connection health and one manual snapshot after the runtime change.

8. **Cleanup/revocation acceptance**
   - In an approved maintenance window or representative clone, verify disconnect/uninstall stops future exports, removes local Catora state, and revoked credentials fail closed.
   - Do not leave the production site disconnected after the acceptance test.

## Done condition

Hilarious is accepted as the first operational closed-loop Catora WordPress site when this sequence is proven:

`publish/change -> automatic snapshot -> change/finding detection -> Review fixes -> explicit approval -> unpublished WordPress draft -> manual publication -> automatic verification scan -> finding improvement/resolution -> ongoing GSC/GA4 measurement`

Record only non-sensitive evidence references and final pass/fail results in issues #202, #204, #205, and #219.
