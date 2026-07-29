<?php

defined( 'ABSPATH' ) || exit;

final class Catora_Service_Visibility {
	private const OPTION = 'catora_service_visibility_settings';
	private const STATUS_OPTION = 'catora_service_visibility_status';
	private const CHECKPOINT_OPTION = 'catora_service_visibility_checkpoint';
	private const CRON_HOOK = 'catora_service_visibility_sync';
	private const BATCH_SIZE = 50;
	private const MAX_PAGE_COUNT = 10000;

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
		$current = $this->settings();
		$endpoint = $this->sanitize_endpoint(
			isset( $input['endpoint'] ) ? trim( (string) $input['endpoint'] ) : '',
			(string) ( $current['endpoint'] ?? '' )
		);
		$source_id = isset( $input['source_id'] ) ? sanitize_text_field( (string) $input['source_id'] ) : '';
		$submitted_token = isset( $input['token'] ) ? trim( (string) $input['token'] ) : '';
		$token = '' !== $submitted_token
			? sanitize_text_field( $submitted_token )
			: (string) ( $current['token'] ?? '' );

		return array(
			'endpoint'              => $endpoint,
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
		$has_token = ! empty( $settings['token'] );
		?>
		<div class="wrap">
			<h1>Catora Service Visibility</h1>
			<p>Only published public content is exported. Forms, users, customers, orders, private posts, passwords, and unpublished content are excluded.</p>
			<form method="post" action="options.php">
				<?php settings_fields( 'catora_service_visibility' ); ?>
				<table class="form-table" role="presentation">
					<tr><th scope="row"><label for="catora-endpoint">Catora endpoint</label></th><td><input class="regular-text" id="catora-endpoint" name="<?php echo esc_attr( self::OPTION ); ?>[endpoint]" type="url" required value="<?php echo esc_attr( (string) ( $settings['endpoint'] ?? '' ) ); ?>"><p class="description">HTTPS is required outside a local development environment.</p></td></tr>
					<tr><th scope="row"><label for="catora-source">Source ID</label></th><td><input class="regular-text" id="catora-source" name="<?php echo esc_attr( self::OPTION ); ?>[source_id]" required value="<?php echo esc_attr( (string) ( $settings['source_id'] ?? '' ) ); ?>"></td></tr>
					<tr><th scope="row"><label for="catora-token">Site token</label></th><td><input class="regular-text" id="catora-token" name="<?php echo esc_attr( self::OPTION ); ?>[token]" type="password" autocomplete="new-password" <?php echo $has_token ? '' : 'required'; ?> value="" placeholder="<?php echo esc_attr( $has_token ? 'Configured — leave blank to keep it' : 'Enter the one-time site token' ); ?>"><p class="description">The saved token is never rendered back into this page. Rotate it from Catora if exposed.</p></td></tr>
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
			$checkpoint = $this->checkpoint();
			if ( array() === $checkpoint ) {
				$checkpoint = $this->prepare_checkpoint( $this->public_records() );
			}

			$snapshot_id = (string) $checkpoint['snapshot_id'];
			$manifest = array(
				'snapshot_id'    => $snapshot_id,
				'page_count'     => (int) $checkpoint['page_count'],
				'started_at'     => (string) $checkpoint['started_at'],
				'site_url'       => home_url(),
				'plugin_version' => CATORA_SERVICE_VISIBILITY_VERSION,
			);
			$status = $this->request( 'POST', $this->path( '/snapshots' ), $manifest, 'snapshot:' . $snapshot_id );
			$accepted_batches = is_array( $status ) ? (int) ( $status['accepted_batches'] ?? 0 ) : 0;
			$batch_count = (int) $checkpoint['batch_count'];
			if ( $accepted_batches < 0 || $accepted_batches > $batch_count ) {
				throw new RuntimeException( 'Catora returned an invalid snapshot checkpoint.' );
			}

			for ( $sequence = $accepted_batches; $sequence < $batch_count; $sequence++ ) {
				$batch_body = $this->checkpoint_batch( $checkpoint, $sequence );
				$status = $this->request(
					'PUT',
					$this->path( '/snapshots/' . rawurlencode( $snapshot_id ) . '/batches/' . $sequence ),
					$batch_body,
					'snapshot:' . $snapshot_id . ':batch:' . str_pad( (string) $sequence, 8, '0', STR_PAD_LEFT )
				);
				$checkpoint['accepted_batches'] = is_array( $status )
					? (int) ( $status['accepted_batches'] ?? ( $sequence + 1 ) )
					: ( $sequence + 1 );
				update_option( self::CHECKPOINT_OPTION, $checkpoint, false );
			}

			$response = $this->request(
				'POST',
				$this->path( '/snapshots/' . rawurlencode( $snapshot_id ) . '/complete' ),
				array(
					'snapshot_id' => $snapshot_id,
					'batch_count' => $batch_count,
					'page_count'  => (int) $checkpoint['page_count'],
				),
				'snapshot:' . $snapshot_id . ':complete'
			);
			$this->cleanup_checkpoint( $checkpoint );
			$this->set_status(
				'Healthy',
				sprintf(
					'Accepted %d public pages. Report ID: %s',
					(int) $manifest['page_count'],
					(string) ( is_array( $response ) ? ( $response['report_id'] ?? 'pending' ) : 'pending' )
				)
			);
			if ( ! empty( $this->settings()['enable_drafts'] ) ) {
				$this->apply_approved_drafts();
			}
		} catch ( Throwable $error ) {
			$this->set_status( 'Failed', $error->getMessage() . ' A retry will resume the last accepted batch when possible.' );
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
					'post_type'           => array_values( $post_types ),
					'post_status'         => 'publish',
					'posts_per_page'      => 100,
					'paged'               => $page,
					'orderby'             => 'ID',
					'order'               => 'ASC',
					'has_password'        => false,
					'ignore_sticky_posts' => true,
					'no_found_rows'       => false,
				)
			);
			foreach ( $query->posts as $post ) {
				if ( ! $post instanceof WP_Post || ! empty( $post->post_password ) ) {
					continue;
				}
				$records[] = $this->record_for_post( $post );
				if ( count( $records ) > self::MAX_PAGE_COUNT ) {
					wp_reset_postdata();
					throw new RuntimeException( 'The site contains more than 10,000 published public records. The snapshot was stopped instead of being silently truncated.' );
				}
			}
			$page++;
		} while ( $page <= (int) $query->max_num_pages );
		wp_reset_postdata();
		return $records;
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
		$yoast_canonical = get_post_meta( $post->ID, '_yoast_wpseo_canonical', true );
		$rank_math_canonical = get_post_meta( $post->ID, 'rank_math_canonical_url', true );
		$yoast_noindex = get_post_meta( $post->ID, '_yoast_wpseo_meta-robots-noindex', true );
		$yoast_nofollow = get_post_meta( $post->ID, '_yoast_wpseo_meta-robots-nofollow', true );
		$rank_math_robots = get_post_meta( $post->ID, 'rank_math_robots', true );
		$robots = array();
		if ( '1' === (string) $yoast_noindex ) {
			$robots[] = 'noindex';
		}
		if ( '1' === (string) $yoast_nofollow ) {
			$robots[] = 'nofollow';
		}
		if ( is_array( $rank_math_robots ) ) {
			$robots = array_merge( $robots, array_map( 'sanitize_text_field', $rank_math_robots ) );
		}
		$builder = get_post_meta( $post->ID, '_elementor_edit_mode', true ) ? 'elementor' : 'gutenberg';
		$permalink = (string) get_permalink( $post );
		$visible_text = wp_strip_all_tags( $content );
		$visible_text = function_exists( 'mb_substr' ) ? mb_substr( $visible_text, 0, 50000 ) : substr( $visible_text, 0, 50000 );
		$author_id = (int) $post->post_author;
		$featured_id = get_post_thumbnail_id( $post );
		$featured = $featured_id ? wp_get_attachment_image_src( $featured_id, 'full' ) : false;

		return array(
			'url'                 => $permalink,
			'canonical_url'       => esc_url_raw( (string) ( $yoast_canonical ?: $rank_math_canonical ?: $permalink ) ),
			'title'               => get_the_title( $post ),
			'meta_description'    => (string) ( $yoast_description ?: $rank_math_description ?: wp_trim_words( $post->post_excerpt, 30, '' ) ),
			'robots'              => implode( ',', array_values( array_unique( array_filter( $robots ) ) ) ),
			'headings'            => $headings,
			'links'               => $links,
			'visible_text'        => $visible_text,
			'json_ld'             => $this->extract_json_ld( $content, $post->ID ),
			'wordpress'           => array(
				'post_id'        => $post->ID,
				'post_type'      => $post->post_type,
				'revision'       => $post->post_modified_gmt,
				'builder'        => $builder,
				'seo_plugin'     => $yoast_description || $yoast_canonical ? 'yoast' : ( $rank_math_description || $rank_math_canonical ? 'rank_math' : null ),
				'author'         => array(
					'id'   => $author_id,
					'name' => (string) get_the_author_meta( 'display_name', $author_id ),
					'url'  => (string) get_author_posts_url( $author_id ),
				),
				'featured_media' => $featured
					? array(
						'url' => (string) $featured[0],
						'alt' => (string) get_post_meta( $featured_id, '_wp_attachment_image_alt', true ),
					)
					: null,
			),
			'source_updated_at' => get_post_modified_time( 'c', true, $post ),
		);
	}

	/**
	 * @return list<array<string, mixed>>
	 */
	private function extract_json_ld( string $content, int $post_id ): array {
		$items = array();
		preg_match_all( '/<script[^>]+type=["\']application\/ld\+json["\'][^>]*>(.*?)<\/script>/is', $content, $matches );
		foreach ( array_slice( $matches[1] ?? array(), 0, 100 ) as $encoded ) {
			$decoded = json_decode( html_entity_decode( trim( (string) $encoded ), ENT_QUOTES | ENT_HTML5, 'UTF-8' ), true );
			$this->append_json_ld( $items, $decoded );
		}
		$all_meta = get_post_meta( $post_id );
		foreach ( $all_meta as $key => $values ) {
			if ( 0 !== strpos( (string) $key, 'rank_math_schema_' ) || ! is_array( $values ) ) {
				continue;
			}
			foreach ( $values as $value ) {
				$decoded = json_decode( (string) maybe_unserialize( $value ), true );
				$this->append_json_ld( $items, $decoded );
			}
		}
		return array_slice( $items, 0, 100 );
	}

	/**
	 * @param list<array<string, mixed>> $items Accumulated JSON-LD objects.
	 * @param mixed $decoded Decoded JSON value.
	 */
	private function append_json_ld( array &$items, $decoded ): void {
		if ( ! is_array( $decoded ) ) {
			return;
		}
		if ( array_is_list( $decoded ) ) {
			foreach ( $decoded as $item ) {
				if ( is_array( $item ) && ! array_is_list( $item ) ) {
					$items[] = $item;
				}
			}
			return;
		}
		$items[] = $decoded;
	}

	/**
	 * @param list<array<string, mixed>> $records Public records.
	 * @return array<string, mixed>
	 */
	private function prepare_checkpoint( array $records ): array {
		$directory = $this->checkpoint_directory();
		if ( ! wp_mkdir_p( $directory ) ) {
			throw new RuntimeException( 'Unable to create the private snapshot checkpoint directory.' );
		}
		@chmod( $directory, 0700 );
		$snapshot_id = wp_generate_uuid4();
		$batch_count = 0;
		foreach ( array_chunk( $records, self::BATCH_SIZE ) as $sequence => $batch ) {
			$body = wp_json_encode(
				array(
					'snapshot_id' => $snapshot_id,
					'sequence'    => $sequence,
					'records'     => $batch,
				),
				JSON_UNESCAPED_SLASHES
			);
			if ( ! is_string( $body ) ) {
				throw new RuntimeException( 'Unable to encode the WordPress snapshot batch.' );
			}
			$file = trailingslashit( $directory ) . sprintf( '%08d.json', $sequence );
			if ( false === file_put_contents( $file, $body, LOCK_EX ) ) {
				throw new RuntimeException( 'Unable to persist a resumable WordPress snapshot batch.' );
			}
			@chmod( $file, 0600 );
			$batch_count++;
		}
		$checkpoint = array(
			'snapshot_id'      => $snapshot_id,
			'started_at'       => gmdate( 'c' ),
			'page_count'       => count( $records ),
			'batch_count'      => $batch_count,
			'accepted_batches' => 0,
			'directory'        => $directory,
		);
		update_option( self::CHECKPOINT_OPTION, $checkpoint, false );
		return $checkpoint;
	}

	/**
	 * @return array<string, mixed>
	 */
	private function checkpoint(): array {
		$value = get_option( self::CHECKPOINT_OPTION, array() );
		if ( ! is_array( $value ) || empty( $value['snapshot_id'] ) || empty( $value['directory'] ) ) {
			return array();
		}
		$batch_count = (int) ( $value['batch_count'] ?? 0 );
		for ( $sequence = 0; $sequence < $batch_count; $sequence++ ) {
			$file = trailingslashit( (string) $value['directory'] ) . sprintf( '%08d.json', $sequence );
			if ( ! is_readable( $file ) ) {
				throw new RuntimeException( 'A resumable snapshot checkpoint file is missing. Contact the Catora operator before starting another snapshot.' );
			}
		}
		return $value;
	}

	/**
	 * @param array<string, mixed> $checkpoint Checkpoint metadata.
	 */
	private function checkpoint_batch( array $checkpoint, int $sequence ): string {
		$file = trailingslashit( (string) $checkpoint['directory'] ) . sprintf( '%08d.json', $sequence );
		$body = file_get_contents( $file );
		if ( ! is_string( $body ) || '' === $body ) {
			throw new RuntimeException( 'Unable to read a resumable WordPress snapshot batch.' );
		}
		return $body;
	}

	private function checkpoint_directory(): string {
		return trailingslashit( get_temp_dir() ) . 'catora-service-visibility-' . substr( hash( 'sha256', ABSPATH ), 0, 16 );
	}

	/**
	 * @param array<string, mixed> $checkpoint Checkpoint metadata.
	 */
	private function cleanup_checkpoint( array $checkpoint ): void {
		$directory = isset( $checkpoint['directory'] ) ? (string) $checkpoint['directory'] : $this->checkpoint_directory();
		if ( is_dir( $directory ) ) {
			$files = glob( trailingslashit( $directory ) . '*' );
			if ( is_array( $files ) ) {
				foreach ( $files as $file ) {
					if ( is_file( $file ) ) {
						@unlink( $file );
					}
				}
			}
			@rmdir( $directory );
		}
		delete_option( self::CHECKPOINT_OPTION );
	}

	private function sanitize_endpoint( string $raw, string $fallback ): string {
		$endpoint = untrailingslashit( esc_url_raw( $raw ) );
		$parts = wp_parse_url( $endpoint );
		$scheme = is_array( $parts ) ? strtolower( (string) ( $parts['scheme'] ?? '' ) ) : '';
		$host = is_array( $parts ) ? strtolower( (string) ( $parts['host'] ?? '' ) ) : '';
		$environment = function_exists( 'wp_get_environment_type' ) ? wp_get_environment_type() : 'production';
		$local_hosts = array( 'localhost', '127.0.0.1', '::1', 'host.docker.internal' );
		$allowed_http = in_array( $environment, array( 'local', 'development', 'test' ), true ) && in_array( $host, $local_hosts, true );
		if ( '' === $host || ( 'https' !== $scheme && ! ( 'http' === $scheme && $allowed_http ) ) ) {
			add_settings_error(
				self::OPTION,
				'catora_service_visibility_endpoint',
				'Use an HTTPS Catora endpoint. Plain HTTP is accepted only for a recognized local development host.',
				'error'
			);
			return $fallback;
		}
		return $endpoint;
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
	 * @param array<string, mixed>|string|null $payload JSON body or pre-encoded JSON.
	 * @return mixed
	 */
	private function request( string $method, string $path, $payload, string $idempotency_key ) {
		$settings = $this->settings();
		$endpoint = untrailingslashit( (string) ( $settings['endpoint'] ?? '' ) );
		$token = (string) ( $settings['token'] ?? '' );
		if ( '' === $endpoint || '' === $token || empty( $settings['source_id'] ) ) {
			throw new RuntimeException( 'Catora endpoint, source ID, and token are required.' );
		}
		$body = is_string( $payload ) ? $payload : ( null === $payload ? '' : (string) wp_json_encode( $payload, JSON_UNESCAPED_SLASHES ) );
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
					'Content-Type'             => 'application/json',
					'X-Catora-Timestamp'       => $timestamp,
					'X-Catora-Content-Sha256'  => $content_hash,
					'X-Catora-Idempotency-Key' => $idempotency_key,
					'X-Catora-Signature'       => $signature,
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
