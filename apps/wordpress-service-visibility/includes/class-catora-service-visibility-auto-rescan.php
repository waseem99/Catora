<?php

defined( 'ABSPATH' ) || exit;

final class Catora_Service_Visibility_Auto_Rescan {
	private const RESCAN_HOOK = 'catora_service_visibility_public_change_rescan';
	private const RESCAN_DELAY_SECONDS = 300;

	private static ?self $instance = null;

	public static function instance(): self {
		if ( null === self::$instance ) {
			self::$instance = new self();
		}
		return self::$instance;
	}

	public static function deactivate(): void {
		wp_clear_scheduled_hook( self::RESCAN_HOOK );
	}

	private function __construct() {
		add_action( 'save_post', array( $this, 'queue_after_public_change' ), 20, 3 );
		add_action( self::RESCAN_HOOK, array( $this, 'run_rescan' ) );
	}

	public function queue_after_public_change( int $post_id, WP_Post $post, bool $update ): void {
		unset( $update );
		if ( 'publish' !== $post->post_status ) {
			return;
		}
		if ( wp_is_post_revision( $post_id ) || wp_is_post_autosave( $post_id ) ) {
			return;
		}
		$post_type = get_post_type_object( $post->post_type );
		if ( ! $post_type || ! $post_type->public ) {
			return;
		}
		if ( false !== wp_next_scheduled( self::RESCAN_HOOK ) ) {
			return;
		}
		wp_schedule_single_event( time() + self::RESCAN_DELAY_SECONDS, self::RESCAN_HOOK );
	}

	public function run_rescan(): void {
		Catora_Service_Visibility::instance()->scheduled_sync();
	}
}
