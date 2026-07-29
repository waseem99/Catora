# WordPress developer integration

## Install

Use the `catora-service-visibility-wordpress-plugin` artifact produced by the Service visibility contract workflow, or build it with:

```bash
bash apps/wordpress-service-visibility/build-plugin.sh
```

Upload the resulting ZIP through **Plugins → Add New Plugin → Upload Plugin**, activate it, and open **Settings → Catora Service Visibility**.

## Configure

Enter the Catora endpoint, source ID, and one-time token supplied by the Catora operator. The endpoint must use HTTPS in production. Treat the token as a backend secret; never put it in a page, frontend JavaScript, analytics system, or public repository.

## Snapshot behavior

The plugin exports published, non-password-protected records from public post types. It includes canonical URL, title, public SEO description, headings, links, rendered visible text, public JSON-LD, post type, post ID, modification timestamp, and detected SEO/page-builder metadata. Batches are deterministically encoded and signed with HMAC-SHA256.

## Draft behavior

Draft delivery is optional and disabled by default. An operator must first approve a proposal in Catora. The plugin verifies the original post's modification timestamp and creates a separate draft. It never publishes automatically and never overwrites the original post or Elementor layout.

## Disconnect

Clear the plugin settings or uninstall it. Uninstall removes Catora plugin options and scheduled events. Ask the Catora operator to rotate/revoke the source token as part of offboarding.
