=== Catora Service Visibility ===
Contributors: catora
Requires at least: 6.4
Requires PHP: 7.4
Stable tag: 0.2.3
License: Proprietary

Exports only published public WordPress content to an authorized Catora workspace for evidence-backed SEO, answer-readiness, and AI-discovery audits.

The authoritative source and publisher record is https://github.com/waseem99/Catora. Repository ownership does not replace authorization from the owner of a WordPress site.

== Safety ==
* Does not export users, forms, customers, orders, private posts, passwords, or drafts.
* Does not publish automatically.
* Approved changes create separate WordPress drafts.
* Does not rewrite Elementor structures.
* Scheduled snapshots are disabled by default.
* When scheduled monitoring is enabled, public content saves queue a bounded follow-up snapshot after five minutes so Catora can verify the changed public state.
* Interrupted snapshots resume from the last accepted batch.
* Disconnect by clearing the settings or uninstalling the plugin.

== Compatibility ==
* PHP 7.4 is supported for controlled legacy pilots.
* PHP 8.3 or newer is recommended before general production use.
