<?php
/**
 * Plugin Name: Catora Service Visibility
 * Description: Read-only export of approved public WordPress content to Catora.
 * Version: 0.1.0
 * Requires at least: 6.6
 * Requires PHP: 8.0
 * Author: Catora
 * License: GPL-2.0-or-later
 */

defined('ABSPATH') || exit;

final class Catora_Service_Visibility {
    private const OPTION_ENDPOINT = 'catora_sv_endpoint';
    private const OPTION_TOKEN = 'catora_sv_token';
    private const OPTION_LAST_SYNC = 'catora_sv_last_sync';
    private const OPTION_LAST_ERROR = 'catora_sv_last_error';
    private const OPTION_SCHEDULED = 'catora_sv_scheduled_enabled';
    private const PROTOCOL = '2026-07-service-visibility-v1';
    private const BATCH_SIZE = 20;
    private const MAX_PAGES = 250;
    private const MAX_VISIBLE_TEXT = 50000;
    private const MAX_STRUCTURED_BLOCKS = 50;
    private const MAX_STRUCTURED_BLOCK_BYTES = 20000;
    private const CRON_HOOK = 'catora_sv_scheduled_sync';
    private const SYNC_LOCK = 'catora_sv_sync_lock';

    public static function boot(): void {
        add_action('admin_menu', [self::class, 'admin_menu']);
        add_action('admin_init', [self::class, 'register_settings']);
        add_action('admin_post_catora_sv_sync', [self::class, 'manual_sync']);
        add_action('admin_post_catora_sv_disconnect', [self::class, 'disconnect']);
        add_action(self::CRON_HOOK, [self::class, 'scheduled_sync']);
        add_action('admin_init', [self::class, 'ensure_schedule']);
    }

    public static function activate(): void {
        add_option(self::OPTION_ENDPOINT, '', '', false);
        add_option(self::OPTION_TOKEN, '', '', false);
        add_option(self::OPTION_LAST_SYNC, '', '', false);
        add_option(self::OPTION_LAST_ERROR, '', '', false);
        add_option(self::OPTION_SCHEDULED, '0', '', false);
    }

    public static function deactivate(): void {
        wp_clear_scheduled_hook(self::CRON_HOOK);
        delete_transient(self::SYNC_LOCK);
    }

    public static function ensure_schedule(): void {
        $endpoint = (string) get_option(self::OPTION_ENDPOINT, '');
        $token = (string) get_option(self::OPTION_TOKEN, '');
        $enabled = (string) get_option(self::OPTION_SCHEDULED, '0') === '1';
        if (!$enabled || $endpoint === '' || $token === '') {
            wp_clear_scheduled_hook(self::CRON_HOOK);
            return;
        }
        if (!wp_next_scheduled(self::CRON_HOOK)) {
            wp_schedule_event(time() + HOUR_IN_SECONDS, 'daily', self::CRON_HOOK);
        }
    }

    public static function scheduled_sync(): void {
        $endpoint = (string) get_option(self::OPTION_ENDPOINT, '');
        $token = (string) get_option(self::OPTION_TOKEN, '');
        if ($endpoint === '' || $token === '') {
            return;
        }
        try {
            self::run_sync();
            update_option(self::OPTION_LAST_SYNC, gmdate('c'), false);
            delete_option(self::OPTION_LAST_ERROR);
        } catch (Throwable $error) {
            update_option(self::OPTION_LAST_ERROR, $error->getMessage(), false);
        }
    }

    public static function register_settings(): void {
        register_setting('catora_sv', self::OPTION_ENDPOINT, [
            'type' => 'string',
            'sanitize_callback' => [self::class, 'sanitize_endpoint'],
            'default' => '',
        ]);
        register_setting('catora_sv', self::OPTION_SCHEDULED, [
            'type' => 'boolean',
            'sanitize_callback' => static fn($value): string => $value ? '1' : '0',
            'default' => '0',
        ]);
        register_setting('catora_sv', self::OPTION_TOKEN, [
            'type' => 'string',
            'sanitize_callback' => [self::class, 'sanitize_token'],
            'default' => '',
        ]);
    }


    public static function sanitize_token(string $value): string {
        $clean = sanitize_text_field($value);
        if ($clean === '') {
            return (string) get_option(self::OPTION_TOKEN, '');
        }
        return $clean;
    }

    public static function sanitize_endpoint(string $value): string {
        $value = esc_url_raw(trim($value));
        if ($value === '' || strtolower((string) wp_parse_url($value, PHP_URL_SCHEME)) !== 'https') {
            add_settings_error('catora_sv', 'endpoint', 'Catora endpoint must use HTTPS.');
            return '';
        }
        return $value;
    }

    public static function admin_menu(): void {
        add_management_page(
            'Catora Service Visibility',
            'Catora Visibility',
            'manage_options',
            'catora-service-visibility',
            [self::class, 'render_admin']
        );
    }

    public static function render_admin(): void {
        if (!current_user_can('manage_options')) {
            return;
        }
        $endpoint = (string) get_option(self::OPTION_ENDPOINT, '');
        $last_sync = (string) get_option(self::OPTION_LAST_SYNC, '');
        $last_error = (string) get_option(self::OPTION_LAST_ERROR, '');
        $scheduled = (string) get_option(self::OPTION_SCHEDULED, '0') === '1';
        ?>
        <div class="wrap">
            <h1>Catora Service Visibility</h1>
            <p>Exports only public pages, posts and public custom post types. It does not read orders, form submissions, private posts, users, passwords or member content, and it never publishes changes.</p>
            <form method="post" action="options.php">
                <?php settings_fields('catora_sv'); ?>
                <table class="form-table" role="presentation">
                    <tr><th scope="row"><label for="catora_sv_endpoint">Catora endpoint</label></th><td><input class="regular-text" type="url" id="catora_sv_endpoint" name="<?php echo esc_attr(self::OPTION_ENDPOINT); ?>" value="<?php echo esc_attr($endpoint); ?>" required></td></tr>
                    <tr><th scope="row"><label for="catora_sv_token">Connection token</label></th><td><input class="regular-text" type="password" id="catora_sv_token" name="<?php echo esc_attr(self::OPTION_TOKEN); ?>" value="" autocomplete="new-password"><p class="description">Leave blank to retain the existing token.</p></td></tr>
                    <tr><th scope="row">Recurring snapshots</th><td><label><input type="checkbox" name="<?php echo esc_attr(self::OPTION_SCHEDULED); ?>" value="1" <?php checked($scheduled); ?>> Enable one daily read-only snapshot</label><p class="description">Leave disabled until recurring monitoring has been approved for this site.</p></td></tr>
                </table>
                <?php submit_button('Save connection'); ?>
            </form>
            <p><strong>Last sync:</strong> <?php echo esc_html($last_sync ?: 'Never'); ?></p>
            <?php if ($last_error !== ''): ?><div class="notice notice-error"><p><?php echo esc_html($last_error); ?></p></div><?php endif; ?>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>" style="display:inline-block;margin-right:12px">
                <input type="hidden" name="action" value="catora_sv_sync"><?php wp_nonce_field('catora_sv_sync'); ?><?php submit_button('Run read-only sync', 'primary', 'submit', false); ?>
            </form>
            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>" style="display:inline-block">
                <input type="hidden" name="action" value="catora_sv_disconnect"><?php wp_nonce_field('catora_sv_disconnect'); ?><?php submit_button('Disconnect', 'secondary', 'submit', false); ?>
            </form>
        </div>
        <?php
    }

    public static function manual_sync(): void {
        if (!current_user_can('manage_options')) {
            wp_die('Unauthorized', 403);
        }
        check_admin_referer('catora_sv_sync');
        try {
            self::run_sync();
            update_option(self::OPTION_LAST_SYNC, gmdate('c'), false);
            delete_option(self::OPTION_LAST_ERROR);
        } catch (Throwable $error) {
            update_option(self::OPTION_LAST_ERROR, $error->getMessage(), false);
        }
        wp_safe_redirect(admin_url('tools.php?page=catora-service-visibility'));
        exit;
    }

    public static function disconnect(): void {
        if (!current_user_can('manage_options')) {
            wp_die('Unauthorized', 403);
        }
        check_admin_referer('catora_sv_disconnect');
        delete_option(self::OPTION_ENDPOINT);
        delete_option(self::OPTION_TOKEN);
        delete_option(self::OPTION_LAST_SYNC);
        delete_option(self::OPTION_LAST_ERROR);
        delete_option(self::OPTION_SCHEDULED);
        wp_clear_scheduled_hook(self::CRON_HOOK);
        delete_transient(self::SYNC_LOCK);
        wp_safe_redirect(admin_url('tools.php?page=catora-service-visibility'));
        exit;
    }

    private static function run_sync(): void {
        if (get_transient(self::SYNC_LOCK)) {
            throw new RuntimeException('A Catora sync is already running.');
        }
        set_transient(self::SYNC_LOCK, '1', 5 * MINUTE_IN_SECONDS);
        try {
            self::send_snapshot();
        } finally {
            delete_transient(self::SYNC_LOCK);
        }
    }

    private static function send_snapshot(): void {
        $endpoint = (string) get_option(self::OPTION_ENDPOINT, '');
        $token = (string) get_option(self::OPTION_TOKEN, '');
        if ($endpoint === '' || $token === '') {
            throw new RuntimeException('Save the Catora endpoint and token before syncing.');
        }
        $pages = self::public_pages();
        if ($pages === []) {
            throw new RuntimeException('No public WordPress content was available to export.');
        }
        $snapshot_id = wp_generate_uuid4();
        $batches = array_chunk($pages, self::BATCH_SIZE);
        foreach ($batches as $sequence => $batch) {
            $payload = [
                'protocolVersion' => self::PROTOCOL,
                'snapshotId' => $snapshot_id,
                'sequence' => $sequence,
                'complete' => $sequence === count($batches) - 1,
                'pages' => $batch,
            ];
            $body = wp_json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
            if (!is_string($body)) {
                throw new RuntimeException('Could not encode the public-content snapshot.');
            }
            $timestamp = (string) time();
            $signature = hash_hmac('sha256', $timestamp . '.' . $body, $token);
            $response = wp_remote_post($endpoint, [
                'timeout' => 30,
                'redirection' => 0,
                'headers' => [
                    'Content-Type' => 'application/json',
                    'X-Catora-Token' => $token,
                    'X-Catora-Timestamp' => $timestamp,
                    'X-Catora-Signature' => $signature,
                ],
                'body' => $body,
                'data_format' => 'body',
            ]);
            if (is_wp_error($response)) {
                throw new RuntimeException($response->get_error_message());
            }
            $status = (int) wp_remote_retrieve_response_code($response);
            if ($status < 200 || $status >= 300) {
                throw new RuntimeException('Catora rejected snapshot batch ' . $sequence . ' with HTTP ' . $status . '.');
            }
        }
    }

    private static function public_pages(): array {
        $post_types = get_post_types(['public' => true], 'names');
        unset($post_types['attachment']);
        $query = new WP_Query([
            'post_type' => array_values($post_types),
            'post_status' => 'publish',
            'posts_per_page' => self::MAX_PAGES,
            'orderby' => 'ID',
            'order' => 'ASC',
            'no_found_rows' => true,
            'ignore_sticky_posts' => true,
        ]);
        $pages = [];
        foreach ($query->posts as $post) {
            if (!($post instanceof WP_Post) || post_password_required($post)) {
                continue;
            }
            $url = get_permalink($post);
            if (!is_string($url) || $url === '') {
                continue;
            }
            $rendered = apply_filters('the_content', $post->post_content);
            $visible = trim(preg_replace('/\s+/u', ' ', wp_strip_all_tags((string) $rendered, true)) ?? '');
            $title = get_the_title($post);
            $head = self::public_head_metadata($url);
            $description = (string) get_post_meta($post->ID, '_yoast_wpseo_metadesc', true);
            if ($description === '') {
                $description = (string) get_post_meta($post->ID, 'rank_math_description', true);
            }
            if ($description === '') {
                $description = (string) ($head['description'] ?? '');
            }
            $canonical = (string) get_post_meta($post->ID, '_yoast_wpseo_canonical', true);
            if ($canonical === '') {
                $canonical = (string) get_post_meta($post->ID, 'rank_math_canonical_url', true);
            }
            if ($canonical === '') {
                $canonical = (string) ($head['canonical'] ?? $url);
            }
            if (!self::same_host($canonical, $url)) {
                $canonical = $url;
            }
            $headings = self::headings((string) $rendered);
            $payload = [
                'id' => (string) $post->ID,
                'url' => $url,
                'canonicalUrl' => $canonical,
                'statusCode' => 200,
                'title' => wp_strip_all_tags((string) $title),
                'metaDescription' => $description !== '' ? wp_strip_all_tags($description) : null,
                'h1' => $headings[0] ?? wp_strip_all_tags((string) $title),
                'headings' => $headings,
                'visibleText' => self::truncate($visible, self::MAX_VISIBLE_TEXT),
                'internalLinks' => self::internal_links((string) $rendered),
                'structuredData' => $head['structuredData'] ?? [],
                'postType' => $post->post_type,
                'author' => get_the_author_meta('display_name', (int) $post->post_author) ?: null,
                'publishedAt' => get_post_datetime($post)?->format(DATE_ATOM),
                'updatedAt' => get_post_datetime($post, 'modified')?->format(DATE_ATOM),
                'robots' => $head['robots'] ?? [],
            ];
            $encoded = wp_json_encode($payload, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
            $payload['contentHash'] = hash('sha256', is_string($encoded) ? $encoded : '');
            $pages[] = $payload;
        }
        wp_reset_postdata();
        return $pages;
    }


    private static function public_head_metadata(string $url): array {
        $result = [
            'canonical' => $url,
            'description' => '',
            'robots' => [],
            'structuredData' => [],
        ];
        $response = wp_safe_remote_get($url, [
            'timeout' => 15,
            'redirection' => 0,
            'limit_response_size' => 2 * MB_IN_BYTES,
            'user-agent' => 'Catora-Service-Visibility-WordPress/0.1.0',
        ]);
        if (is_wp_error($response) || (int) wp_remote_retrieve_response_code($response) !== 200) {
            return $result;
        }
        $body = (string) wp_remote_retrieve_body($response);
        if (preg_match('/<link[^>]+rel=["\'][^"\']*canonical[^"\']*["\'][^>]+href=["\']([^"\']+)["\']/i', $body, $match)) {
            $candidate = esc_url_raw(html_entity_decode((string) $match[1], ENT_QUOTES | ENT_HTML5, 'UTF-8'));
            if ($candidate !== '' && self::same_host($candidate, $url)) {
                $result['canonical'] = $candidate;
            }
        }
        if (preg_match('/<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']*)["\']/i', $body, $match)) {
            $result['description'] = sanitize_text_field(html_entity_decode((string) $match[1], ENT_QUOTES | ENT_HTML5, 'UTF-8'));
        }
        if (preg_match('/<meta[^>]+name=["\']robots["\'][^>]+content=["\']([^"\']*)["\']/i', $body, $match)) {
            $directives = array_filter(array_map('trim', explode(',', strtolower((string) $match[1]))));
            $result['robots'] = array_values(array_unique($directives));
        }
        if (preg_match_all('/<script[^>]+type=["\']application\/ld\+json["\'][^>]*>(.*?)<\/script>/is', $body, $matches)) {
            foreach ($matches[1] ?? [] as $raw) {
                $decoded = json_decode(html_entity_decode((string) $raw, ENT_QUOTES | ENT_HTML5, 'UTF-8'), true);
                if (is_array($decoded)) {
                    $blocks = array_is_list($decoded) ? $decoded : [$decoded];
                    foreach ($blocks as $block) {
                        $encoded = wp_json_encode($block, JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
                        if (
                            is_array($block)
                            && is_string($encoded)
                            && strlen($encoded) <= self::MAX_STRUCTURED_BLOCK_BYTES
                            && count($result['structuredData']) < self::MAX_STRUCTURED_BLOCKS
                        ) {
                            $result['structuredData'][] = $block;
                        }
                    }
                }
            }
        }
        return $result;
    }

    private static function same_host(string $candidate, string $reference): bool {
        return strtolower((string) wp_parse_url($candidate, PHP_URL_HOST)) === strtolower((string) wp_parse_url($reference, PHP_URL_HOST));
    }

    private static function truncate(string $value, int $length): string {
        return function_exists('mb_substr') ? mb_substr($value, 0, $length) : substr($value, 0, $length);
    }

    private static function headings(string $html): array {
        preg_match_all('/<h[1-6][^>]*>(.*?)<\/h[1-6]>/is', $html, $matches);
        $headings = [];
        foreach ($matches[1] ?? [] as $value) {
            $clean = trim(preg_replace('/\s+/u', ' ', wp_strip_all_tags((string) $value)) ?? '');
            if ($clean !== '') {
                $headings[] = self::truncate($clean, 2000);
            }
        }
        return array_slice($headings, 0, 500);
    }

    private static function internal_links(string $html): array {
        preg_match_all('/<a\s[^>]*href=["\']([^"\']+)["\']/i', $html, $matches);
        $home_host = strtolower((string) wp_parse_url(home_url('/'), PHP_URL_HOST));
        $links = [];
        foreach ($matches[1] ?? [] as $href) {
            $raw = (string) $href;
            $url = str_starts_with($raw, '/') ? home_url($raw) : esc_url_raw($raw);
            if ($url === '' || !wp_http_validate_url($url)) {
                continue;
            }
            if (strtolower((string) wp_parse_url($url, PHP_URL_HOST)) === $home_host) {
                $links[$url] = true;
            }
        }
        return array_slice(array_keys($links), 0, 5000);
    }
}

register_activation_hook(__FILE__, [Catora_Service_Visibility::class, 'activate']);
register_deactivation_hook(__FILE__, [Catora_Service_Visibility::class, 'deactivate']);
Catora_Service_Visibility::boot();
