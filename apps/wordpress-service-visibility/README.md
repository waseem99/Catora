# Catora Service Visibility WordPress bridge

Current release: **0.2.3**.

This plugin is optional. Catora can run a zero-install audit from an authorized public WordPress sitemap, while the bridge provides deterministic page metadata, resumable snapshots, connection health, optional scheduled snapshots, approved draft delivery, and post-change verification scans.

The authoritative source and repository-side publisher record is [`waseem99/Catora`](https://github.com/waseem99/Catora). That repository authority verifies plugin provenance; it does not replace permission from the owner or authorized representative of the WordPress site where the plugin is installed.

## Install

1. Build or download `catora-service-visibility.zip`.
2. In WordPress, open **Plugins → Add New Plugin → Upload Plugin**.
3. Activate the plugin.
4. Open **Settings → Catora Service Visibility**.
5. Enter the HTTPS Catora endpoint, source ID, and one-time site token.
6. Save and run the read-only snapshot.

The token must be supplied through an approved secret channel. Once saved, it is not rendered back into the settings form. Rotate it in Catora if it is exposed.

Scheduled snapshots are disabled by default. Manual snapshots remain available; enable the daily schedule only after the site owner and Catora operator approve recurring monitoring. Once monitoring is enabled, saving published public content queues one bounded follow-up snapshot after five minutes. This lets Catora compare the new public state with the prior report and verify new, changed and removed pages as well as new and resolved findings. Interrupted uploads retain private temporary batch checkpoints outside the public WordPress web root and resume from the last batch accepted by Catora.

## PHP compatibility

The bridge supports PHP 7.4 so authorized legacy WordPress pilots can install it. PHP 7.4 is end-of-life, so the plugin displays an administrator warning and PHP 8.3 or newer should be used before general production operation. Release validation exercises installation, activation, signed snapshot delivery, forced interruption, resume, metadata extraction, and uninstall cleanup on PHP 7.4 as well as the primary PHP 8.3 runtime.

## Data boundary

Only published, non-password-protected records from public post types are exported. The plugin excludes attachments as records, users as records, forms, members, customers, orders, private content, and unpublished content. It includes page URLs, supported Yoast/Rank Math metadata, headings, links, visible text, authorship, featured-media metadata, and JSON-LD found in rendered content or Rank Math schema metadata.

A snapshot fails explicitly if the site exceeds the Catora bridge limit of 10,000 published public records; it is never silently truncated.

Draft delivery is disabled unless both Catora and WordPress settings allow it. Approved proposals create a new unpublished draft; they never update or publish the original page. Elementor structures are not rewritten.
