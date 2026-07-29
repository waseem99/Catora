<?php

defined( 'ABSPATH' ) || exit;

final class Catora_Service_Visibility {
	private const OPTION = 'catora_service_visibility_settings';
	private const STATUS_OPTION = 'catora_service_visibility_status';
	private const CRON_HOOK = 'catora_service_visibility_sync';
	private const BATCH_SIZE = 50;

	private static ?self $instance = null;

	public static function instance(): self {
		if ( null === self::$instance ) {
			self::$instance = new self();
		}
		return self::$instance;
	}

	public static function activate(): void {
		wp_clear_scheduled_hook( self::CRON_HOOK );
	}

	public static function deactivate(): void {
		wp_clear_scheduled_hook( self::CRON_HOOK );
	}

	private function __construct() {
		add_action( 'admin_menu', array( $this, 'admin_menu' ) );
		add_action( 'admin_init', array( $this, 'register_settings' ) );
		add_action( 'admin_init', array( $this, 'reconcile_schedule' ), 20 );
		add_action( 'admin_post_catora_service_visibility_sync', array( $this, 'manual_sync' ) );
		add_action( self::CRON_HOOK, array( $this, 'scheduled_sync' ) );
	}

	public function register_settings(): void {
		register_setting(
			'catora_service_visibility',
			self::OPTION,
			array(
				'type'              => 'array',
				'sanitize_callback' => array( $this, 'sanitize_settings' ),
				'default'           => array(),
			)
		);
	}

	/**
	 * @param mixed $value Raw settings.
	 * @return array<string, mixed>
	 */
	public function sanitize_settings( $value ): array {
		$input = is_array( $value ) ? $value : array();
		$endpoint = isset( $input['endpoint'] ) ? esc_url_raw( trim( (string) $input['endpoint'] ) ) : '';
		$source_id = isset( $input['source_id'] ) ? sanitize_text_field( (string) $input['source_id'] ) : '';
		$token = isset( $input['token'] ) ? sanitize_text_field( (string) $input['token'] ) : '';
		return array(
			'endpoint'              => untrailingslashit( $endpoint ),
			'source_id'             => $source_id,
			'token'                 => $token,
			'enable_scheduled_sync' => ! empty( $input['enable_scheduled_sync'] ),
			'enable_drafts'         => ! empty( $input['enable_drafts'] ),
		);
	}

	public function admin_menu(): void {
		add_options_page(
			'Catora Service Visibility',
			'Catora Service Visibility',
			'manage_options',
			'catora-service-visibility',
			array( $this, 'render_admin_page' )
		);
	}

	public function render_admin_page(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			return;
		}
		$settings = $this->settings();
		$status = get_option( self::STATUS_OPTION, array() );
		?>
		<div class="wrap">
			<h1>Catora Service Visibility</h1>
			<p>Only published public content is exported. Forms, users, customers, orders, private posts, passwords, and unpublished content are excluded.</p>
			<form method="post" action="options.php">
				<?php settings_fields( 'catora_service_visibility' ); ?>
				<table class="form-table" role="presentation">
					<tr><th scope="row"><label for="catora-endpoint">Catora endpoint</label></th><td><input class="regular-text" id="catora-endpoint" name="<?php echo esc_attr( self::OPTION ); ?>[endpoint]" type="url" required value="<?php echo esc_attr( (string) ( $settings['endpoint'] ?? '' ) ); ?>"></td></tr>
					<tr><th scope="row"><label for="catora-source">Source ID</label></th><td><input class="regular-text" id="catora-source" name="<?php echo esc_attr( self::OPTION ); ?>[source_id]" required value="<?php echo esc_attr( (string) ( $settings['source_id'] ?? '' ) ); ?>"></td></tr>
					<tr><th scope="row"><label for="catora-token">Site token</label></th><td><input class="regular-text" id="catora-token" name="<?php echo esc_attr( self::OPTION ); ?>[token]" type="password" autocomplete="new-password" required value="<?php echo esc_attr( (string) ( $settings['token'] ?? '' ) ); ?>"><p class="description">Use the one-time token provided by the Catora workspace operator. Rotate it from Catora if exposed.</p></td></tr>
					<tr><th scope="row">Scheduled snapshots</th><td><label><input name="<?php echo esc_attr( self::OPTION ); ?>[enable_scheduled_sync]" type="checkbox" value="1" <?php checked( ! empty( $settings['enable_scheduled_sync'] ) ); ?>> Run one read-only snapshot daily</label><p class="description">Disabled by default. Enable only after the site owner and Catora operator approve recurring monitoring.</p></td></tr>
					<tr><th scope="row">Approved drafts</th><td><label><input name="<?php echo esc_attr( self::OPTION ); ?>[enable_drafts]" type="checkbox" value="1" <?php checked( ! empty( $settings['enable_drafts'] ) ); ?>> Create unpublished draft copies for proposals explicitly approved in Catora</label></td></tr>
				</table>
				<?php submit_button( 'Save connection' ); ?>
			</form>
			<hr>
			<h2>Connection health</h2>
			<p><strong>Status:</strong> <?php echo esc_html( (string) ( $status['status'] ?? 'Not synchronized' ) ); ?></p>
			<?php if ( ! empty( $status['updated_at'] ) ) : ?><p><strong>Last attempt:</strong> <?php echo esc_html( (string) $status['updated_at'] ); ?></p><?php endif; ?>
			<?php if ( ! empty( $status['detail'] ) ) : ?><p><?php echo esc_html( (string) $status['detail'] ); ?></p><?php endif; ?>
			<form method="post" action="<?php echo esc_url( admin_url( 'admin-post.php' ) ); ?>">
				<input type="hidden" name="action" value="catora_service_visibility_sync">
				<?php wp_nonce_field( 'catora_service_visibility_sync' ); ?>
				<?php submit_button( 'Run read-only snapshot now', 'secondary' ); ?>
			</form>
			<p><em>Catora never publishes automatically. Elementor structures are never rewritten by this plugin.</em></p>
		</div>
		<?php
	}

	public function manual_sync(): void {
		if ( ! current_user_can( 'manage_options' ) ) {
			wp_die( esc_html__( 'Insufficient permissions.', 'catora-service-visibility' ) );
		}
		check_admin_referer( 'catora_service_visibility_sync' );
		$this->sync();
		wp_safe_redirect( admin_url( 'options-general.php?page=catora-service-visibility' ) );
		exit;
	}

	public function reconcile_schedule(): void {
		$enabled = ! empty( $this->settings()['enable_scheduled_sync'] );
		$scheduled = wp_next_scheduled( self::CRON_HOOK );
		if ( $enabled && false === $scheduled ) {
			wp_schedule_event( time() + 300, 'daily', self::CRON_HOOK );
		} elseif ( ! $enabled && false !== $scheduled ) {
			wp_clear_scheduled_hook( self::CRON_HOOK );
		}
	}

	public function scheduled_sync(): void {
		if ( empty( $this->settings()['enable_scheduled_sync'] ) ) {
			wp_clear_scheduled_hook( self::CRON_HOOK );
			return;
		}
		$this->sync();
	}

	public function sync(): void {
		try {
			$records = $this->public_records();
			$snapshot_id = wp_generate_uuid4();
			$manifest = array(
				'snapshot_id'   => $snapshot_id,
				'page_count'    => count( $records ),
				'started_at'    => gmdate( 'c' ),
				'site_url'      => home_url(),
				'plugin_version'=> CATORA_SERVICE_VISIBILITY_VERSION,
			);
			$this->request( 'POST', $this->path( '/snapshots' ), $manifest, 'snapshot:' . $snapshot_id );
			$batches = array_chunk( $records, self::BATCH_SIZE );
			foreach ( $batches as $sequence => $batch ) {
				$this->request(
					'PUT',
					$this->path( '/snapshots/' . rawurlencode( $snapshot_id ) . '/batches/' . $sequence ),
					array(
						'snapshot_id' => $snapshot_id,
						'sequence'    => $sequence,
						'records'     => $batch,
					),
					'snapshot:' . $snapshot_id . ':batch:' . str_pad( (string) $sequence, 8, '0', STR_PAD_LEFT )
				);
			}
			$response = $this->request(
				'POST',
				$this->path( '/snapshots/' . rawurlencode( $snapshot_id ) . '/complete' ),
				array(
					'snapshot_id' => $snapshot_id,
					'batch_count' => count( $batches ),
					'page_count'  => count( $records ),
				),
				'snapshot:' . $snapshot_id . ':complete'
			);
			$this->set_status( 'Healthy', sprintf( 'Accepted %d public pages. Report ID: %s', count( $records ), (string) ( $response['report_id'] ?? 'pending' ) ) );
			if ( ! empty( $this->settings()['enable_drafts'] ) ) {
				$this->apply_approved_drafts();
			}
		} catch ( Throwable $error ) {
			$this->set_status( 'Failed', $error->getMessage() );
		}
	}

	/**
	 * @return list<array<string, mixed>>
	 */
	private function public_records(): array {
		$post_types = get_post_types( array( 'public' => true ), 'names' );
		unset( $post_types['attachment'] );
		$records = array();
		$page = 1;
		do {
			$query = new WP_Query(
				array(
					'post_type'      => array_values( $post_types ),
					'post_status'    => 'publish',
					'posts_per_page' => 100,
					'paged'          => $page,
					'orderby'        => 'ID',
					'order'          => 'ASC',
					'has_password'   => false,
					'no_found_rows'  => false,
				)
			);
			foreach ( $query->posts as $post ) {
				if ( ! $post instanceof WP_Post || ! empty( $post->post_password ) ) {
					continue;
				}
				$records[] = $this->record_for_post( $post );
			}
			$page++;
		} while ( $page <= (int) $query->max_num_pages && count( $records ) < 1000 );
		wp_reset_postdata();
		return array_slice( $records, 0, 1000 );
	}

	/**
	 * @return array<string, mixed>
	 */
	private function record_for_post( WP_Post $post ): array {
		$content = apply_filters( 'the_content', $post->post_content );
		preg_match_all( '/<h([1-6])[^>]*>(.*?)<\/h\1>/is', $content, $heading_matches, PREG_SET_ORDER );
		$headings = array();
		foreach ( array_slice( $heading_matches, 0, 200 ) as $match ) {
			$headings[] = array( 'level' => 'h' . $match[1], 'text' => wp_strip_all_tags( $match[2] ) );
		}
		preg_match_all( '/<a[^>]+href=["\']([^"\']+)["\']/i', $content, $link_matches );
		$links = array_values( array_unique( array_slice( $link_matches[1] ?? array(), 0, 2000 ) ) );
		$yoast_description = get_post_meta( $post->ID, '_yoast_wpseo_metadesc', true );
		$rank_math_description = get_post_meta( $post->ID, 'rank_math_description', true );
		$noindex = get_post_meta( $post->ID, '_yoast_wpseo_meta-robots-noindex', true );
		$builder = get_post_meta( $post->ID, '_elementor_edit_mode', true ) ? 'elementor' : 'gutenberg';
		return array(
			'url'                => get_permalink( $post ),
			'canonical_url'      => get_permalink( $post ),
			'title'              => get_the_title( $post ),
			'meta_description'   => (string) ( $yoast_description ?: $rank_math_description ?: wp_trim_words( $post->post_excerpt, 30, '' ) ),
			'robots'             => '1' === (string) $noindex ? 'noindex' : '',
			'headings'           => $headings,
			'links'              => $links,
			'visible_text'       => mb_substr( wp_strip_all_tags( $content ), 0, 50000 ),
			'json_ld'            => array(),
			'wordpress'          => array(
				'post_id'      => $post->ID,
				'post_type'    => $post->post_type,
				'revision'     => $post->post_modified_gmt,
				'builder'      => $builder,
				'seo_plugin'   => $yoast_description ? 'yoast' : ( $rank_math_description ? 'rank_math' : null ),
			),
			'source_updated_at' => gmdate( 'c', strtotime( $post->post_modified_gmt . ' GMT' ) ),
		);
	}

	private function apply_approved_drafts(): void {
		$drafts = $this->request( 'GET', $this->path( '/drafts' ), null, 'drafts:' . gmdate( 'YmdH' ) );
		if ( ! is_array( $drafts ) ) {
			return;
		}
		foreach ( $drafts as $draft ) {
			if ( ! is_array( $draft ) || empty( $draft['id'] ) || empty( $draft['wordpress_post_id'] ) ) {
				continue;
			}
			$this->apply_draft( $draft );
		}
	}

	/**
	 * @param array<string, mixed> $draft Draft payload.
	 */
	private function apply_draft( array $draft ): void {
		$proposal_id = sanitize_text_field( (string) $draft['id'] );
		$existing = get_posts(
			array(
				'post_type'      => 'any',
				'post_status'    => 'draft',
				'posts_per_page' => 1,
				'fields'         => 'ids',
				'meta_key'       => '_catora_proposal_id',
				'meta_value'     => $proposal_id,
			)
		);
		if ( ! empty( $existing ) ) {
			$this->request(
				'POST',
				$this->path( '/drafts/' . rawurlencode( $proposal_id ) . '/result' ),
				array( 'status' => 'applied', 'remote_draft_id' => (int) $existing[0] ),
				'draft-result:' . $proposal_id
			);
			return;
		}

		$post = get_post( (int) $draft['wordpress_post_id'] );
		$result = array( 'status' => 'failed', 'error' => 'Original post is unavailable.' );
		if ( $post instanceof WP_Post ) {
			if ( (string) $post->post_modified_gmt !== (string) ( $draft['base_revision'] ?? '' ) ) {
				$result = array( 'status' => 'stale', 'error' => 'The original post changed after approval.' );
			} else {
				$proposal = is_array( $draft['proposal'] ?? null ) ? $draft['proposal'] : array();
				$is_elementor = (bool) get_post_meta( $post->ID, '_elementor_edit_mode', true );
				$content = $is_elementor ? $post->post_content : (string) ( $proposal['content'] ?? $post->post_content );
				$draft_id = wp_insert_post(
					array(
						'post_type'    => $post->post_type,
						'post_status'  => 'draft',
						'post_parent'  => $post->ID,
						'post_title'   => (string) ( $proposal['title'] ?? $post->post_title ),
						'post_content' => $content,
						'post_excerpt' => $post->post_excerpt,
					),
					true
				);
				if ( is_wp_error( $draft_id ) ) {
					$result = array( 'status' => 'failed', 'error' => $draft_id->get_error_message() );
				} else {
					update_post_meta( $draft_id, '_catora_source_post_id', $post->ID );
					update_post_meta( $draft_id, '_catora_proposal_id', $proposal_id );
					update_post_meta( $draft_id, '_catora_proposed_meta_title', sanitize_text_field( (string) ( $proposal['meta_title'] ?? '' ) ) );
					update_post_meta( $draft_id, '_catora_proposed_meta_description', sanitize_textarea_field( (string) ( $proposal['meta_description'] ?? '' ) ) );
					update_post_meta( $draft_id, '_catora_proposed_structured_data', wp_json_encode( $proposal['structured_data'] ?? null ) );
					update_post_meta( $draft_id, '_catora_proposed_internal_links', wp_json_encode( $proposal['internal_links'] ?? array() ) );
					if ( $is_elementor ) {
						update_post_meta( $draft_id, '_catora_review_note', 'Elementor structure was not modified. Review the proposal metadata and content brief manually.' );
					}
					$result = array( 'status' => 'applied', 'remote_draft_id' => (int) $draft_id );
				}
			}
		}
		$this->request( 'POST', $this->path( '/drafts/' . rawurlencode( $proposal_id ) . '/result' ), $result, 'draft-result:' . $proposal_id );
	}

	private function path( string $suffix ): string {
		$source_id = rawurlencode( (string) ( $this->settings()['source_id'] ?? '' ) );
		return '/api/v1/service-visibility/sources/' . $source_id . $suffix;
	}

	/**
	 * @param array<string, mixed>|null $payload JSON body.
	 * @return mixed
	 */
	private function request( string $method, string $path, ?array $payload, string $idempotency_key ) {
		$settings = $this->settings();
		$endpoint = untrailingslashit( (string) ( $settings['endpoint'] ?? '' ) );
		$token = (string) ( $settings['token'] ?? '' );
		if ( '' === $endpoint || '' === $token || empty( $settings['source_id'] ) ) {
			throw new RuntimeException( 'Catora endpoint, source ID, and token are required.' );
		}
		$body = null === $payload ? '' : (string) wp_json_encode( $payload );
		$timestamp = (string) time();
		$content_hash = hash( 'sha256', $body );
		$canonical = strtoupper( $method ) . "\n" . $path . "\n" . $timestamp . "\n" . $content_hash . "\n" . $idempotency_key;
		$signature = rtrim( strtr( base64_encode( hash_hmac( 'sha256', $canonical, $token, true ) ), '+/', '-_' ), '=' );
		$response = wp_remote_request(
			$endpoint . $path,
			array(
				'method'  => strtoupper( $method ),
				'timeout' => 45,
				'headers' => array(
					'Content-Type'            => 'application/json',
					'X-Catora-Timestamp'      => $timestamp,
					'X-Catora-Content-Sha256' => $content_hash,
					'X-Catora-Idempotency-Key'=> $idempotency_key,
					'X-Catora-Signature'      => $signature,
				),
				'body'    => $body,
			)
		);
		if ( is_wp_error( $response ) ) {
			throw new RuntimeException( $response->get_error_message() );
		}
		$code = (int) wp_remote_retrieve_response_code( $response );
		$decoded = json_decode( (string) wp_remote_retrieve_body( $response ), true );
		if ( $code < 200 || $code >= 300 ) {
			$detail = is_array( $decoded ) && isset( $decoded['detail'] ) ? wp_json_encode( $decoded['detail'] ) : 'HTTP ' . $code;
			throw new RuntimeException( 'Catora request failed: ' . $detail );
		}
		return $decoded;
	}

	/**
	 * @return array<string, mixed>
	 */
	private function settings(): array {
		$value = get_option( self::OPTION, array() );
		return is_array( $value ) ? $value : array();
	}

	private function set_status( string $status, string $detail ): void {
		update_option(
			self::STATUS_OPTION,
			array(
				'status'     => $status,
				'detail'     => $detail,
				'updated_at' => gmdate( 'c' ),
			),
			false
		);
	}
}
