# Catora Service Visibility WordPress bridge

This plugin is optional. Catora can run a zero-install audit from an authorized public WordPress sitemap, while the bridge provides deterministic page metadata, scheduled snapshots, connection health, and approved draft delivery.

## Install

1. Build or download `catora-service-visibility.zip`.
2. In WordPress, open **Plugins → Add New Plugin → Upload Plugin**.
3. Activate the plugin.
4. Open **Settings → Catora Service Visibility**.
5. Enter the Catora endpoint, source ID, and one-time site token.
6. Save and run the read-only snapshot.

The token must be supplied through an approved secret channel. Rotate it in Catora if it is exposed.

Scheduled snapshots are disabled by default. Manual snapshots remain available; enable the daily schedule only after the site owner and Catora operator approve recurring monitoring. Draft delivery reuses an existing local draft for the same Catora proposal if a result callback must be retried.

## Data boundary

Only published public posts and public post types are exported. The plugin excludes attachments, password-protected posts, users, forms, members, customers, orders, and private content.

Draft delivery is disabled unless both Catora and WordPress settings allow it. Approved proposals create a new unpublished draft; they never update or publish the original page. Elementor structures are not rewritten.
