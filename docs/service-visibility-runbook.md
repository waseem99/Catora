# Catora Service Visibility runbook

## Release boundary

This release is a read-only audit for authorized technology and professional-services websites. It supports:

- zero-install, exact-host public crawling with robots, redirect, DNS and response-size controls;
- a thin WordPress bridge for public pages, posts and public post types;
- deterministic page classification, entity extraction and versioned findings;
- a deterministic 25-question buyer-coverage suite;
- editable CSV, PPTX and content-brief artifacts;
- content-addressed source evidence and workspace-scoped report artifacts;
- manual re-scan and an explicit, disabled-by-default daily snapshot control.

It does not access forms, orders, customers, users, private content or raw WordPress database rows. It does not publish or edit pages. Draft creation remains unavailable. Recurring snapshots stay disabled until the site owner approves monitoring; broader change-impact reporting remains gated by issue #205.

## Zero-install acceptance

1. Obtain written authorization for the exact domain.
2. Create a `zero_install` Service Visibility source.
3. Start a run and confirm redirects, canonicals and discovered links never leave the approved host.
4. Review the latest scorecard, all exact-page evidence and 25 buyer questions.
5. Generate CSV, PPTX and content brief artifacts.

## WordPress bridge acceptance

1. Create a `wordpress_bridge` source and copy the endpoint/token once.
2. Download the plugin ZIP produced by the Service visibility contract workflow.
3. Install it on a clean supported WordPress site.
4. Enter the HTTPS endpoint and token under Tools > Catora Visibility.
5. Run a manual sync; confirm batches are signed, sequential, checksum-protected and idempotent.
6. Leave daily snapshots disabled unless recurring monitoring has been approved.
7. Disconnect and verify local connection options and scheduled exports are removed.

## Real pilot gate (#203)

Repository tests cannot substitute for two authorized real-site pilots. Keep #203 open until:

- one site uses zero-install and one uses the plugin;
- owners review findings and false positives;
- a small approved remediation set is implemented;
- before/after evidence is produced;
- commercial willingness and a proceed/change/stop decision are recorded.
