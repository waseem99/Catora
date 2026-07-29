# WordPress developer integration

## Install

Use the `catora-service-visibility-wordpress-plugin` artifact produced by the Service visibility contract workflow, or build it with:

```bash
bash apps/wordpress-service-visibility/build-plugin.sh
```

Upload the resulting ZIP through **Plugins → Add New Plugin → Upload Plugin**, activate it, and open **Settings → Catora Service Visibility**.

## Configure

Enter the Catora endpoint, source ID, and one-time token supplied by the Catora operator. The endpoint must use HTTPS in production. Plain HTTP is accepted only for recognized local-development hosts. Treat the token as a backend secret; never put it in a page, frontend JavaScript, analytics system, or public repository. The settings screen never renders the saved token back to the browser.

## Snapshot behavior

The plugin exports published, non-password-protected records from public post types. It includes canonical URL, title, public SEO description, robots metadata, headings, links, rendered visible text, authorship, featured-media metadata, public JSON-LD found in rendered content or supported Rank Math schema metadata, post type, post ID, modification timestamp, and detected SEO/page-builder metadata.

Batches are deterministically encoded and signed with HMAC-SHA256. Before transmission, the plugin stores private temporary batch files outside the public web root. If a request or PHP process is interrupted, the next manual or scheduled run reuses the same snapshot ID and resumes from the number of batches Catora already accepted. The checkpoint is deleted after successful completion and on plugin uninstall.

Catora currently accepts at most 10,000 published public records per bridge snapshot. Larger sites fail with an explicit error rather than returning an incomplete snapshot.

## Draft behavior

Draft delivery is optional and disabled by default. An operator must first approve a proposal in Catora. The plugin verifies the original post's modification timestamp and creates a separate draft. It never publishes automatically and never overwrites the original post or Elementor layout.

## Disconnect

Clear the plugin settings or uninstall it. Uninstall removes Catora plugin options, resumable checkpoint files, and scheduled events. Ask the Catora operator to rotate or revoke the source token as part of offboarding.

## Automated acceptance

The Service visibility contract workflow builds the exact installable ZIP, installs it on a clean WordPress and MariaDB runtime, verifies activation and default-disabled scheduling, injects 55 published records, forces a one-time batch interruption, proves checkpointed resume, verifies signed delivery and metadata extraction, and confirms uninstall cleanup.
