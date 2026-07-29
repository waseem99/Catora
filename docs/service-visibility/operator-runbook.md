# Service Visibility operator runbook

## Production configuration

Set the following on both the API and worker, using the same URL-safe base64 value encoding exactly 32 random bytes:

```text
CATORA_SERVICE_VISIBILITY_ENABLED=true
CATORA_SERVICE_VISIBILITY_CREDENTIAL_ENCRYPTION_KEY=<secret>
```

Keep these disabled until a pilot explicitly requires them:

```text
CATORA_SERVICE_VISIBILITY_DRAFTS_ENABLED=false
CATORA_SERVICE_VISIBILITY_MONITORING_ENABLED=false
```

Deploy API and worker from the same merged commit. The API deployment must apply Alembic migration `0019` before serving traffic.

## Zero-install pilot

1. Obtain written authorization for the exact domain.
2. Create a source using its HTTPS site or sitemap URL and confirm authorization.
3. Keep monitoring disabled.
4. Run the audit and reconcile the discovered public-page count with the sitemap scope.
5. Review the evidence JSON, findings CSV, buyer-question CSV, brief, and presentation.
6. Select a small remediation set with the site owner.
7. Re-run after implementation and preserve before/after evidence.

## Plugin-assisted pilot

1. Create a WordPress bridge source in the correct workspace.
2. Deliver endpoint, source ID, and one-time token through an approved secret channel.
3. Install the workflow-produced ZIP through WordPress Admin.
4. Run a manual read-only snapshot and reconcile published public post types.
5. Rotate the token immediately if it is exposed.
6. Enable draft delivery only after explicit approval and only for separate unpublished drafts.

## Rollback

Disable the service visibility flags, stop scheduled plugin sync, rotate or revoke the site credential, and deactivate/uninstall the plugin. Existing reports and immutable evidence remain available according to Catora retention policy. The connector does not need to remain active for the website to operate.
