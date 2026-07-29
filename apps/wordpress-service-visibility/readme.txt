=== Catora Service Visibility ===
Contributors: catora
Tags: seo, aeo, service visibility, audit
Requires at least: 6.6
Requires PHP: 8.0
Stable tag: 0.1.0
License: GPLv2 or later

Read-only public-content bridge for an approved Catora Service Visibility source.

== Description ==

The plugin exports approved public pages, posts and public custom post types to Catora using signed, ordered and idempotent batches. It does not access ecommerce orders, form submissions, private or password-protected content, users, passwords or member data. It never publishes or edits WordPress content.

Manual sync is available after connection. Daily read-only snapshots are disabled by default and must be explicitly enabled only after recurring monitoring has been approved for the site.

== Installation ==

1. Upload and activate the plugin ZIP.
2. Open Tools > Catora Visibility.
3. Enter the HTTPS endpoint and one-time connection token provided by Catora.
4. Save and run the read-only sync.
5. Leave recurring snapshots disabled unless they have been approved.
6. Disconnect to remove local Catora connection state and scheduled exports.

== Changelog ==

= 0.1.0 =
* Initial read-only public-content bridge.
