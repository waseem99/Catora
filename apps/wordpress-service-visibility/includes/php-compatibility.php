<?php

defined( 'ABSPATH' ) || exit;

if ( ! function_exists( 'array_is_list' ) ) {
	/**
	 * PHP 7.4-compatible implementation of array_is_list().
	 *
	 * @param array<mixed> $value Value to inspect.
	 */
	function array_is_list( array $value ): bool {
		$expected_key = 0;
		foreach ( $value as $key => $_item ) {
			if ( $expected_key !== $key ) {
				return false;
			}
			$expected_key++;
		}
		return true;
	}
}

/**
 * Warn administrators when the bridge is running on legacy PHP.
 */
function catora_service_visibility_legacy_php_notice(): void {
	if ( ! current_user_can( 'manage_options' ) || version_compare( PHP_VERSION, '8.3', '>=' ) ) {
		return;
	}
	?>
	<div class="notice notice-warning">
		<p>
			<strong>Catora Service Visibility:</strong>
			This server is running PHP <?php echo esc_html( PHP_VERSION ); ?>.
			PHP 7.4 is supported for controlled legacy pilots, but it is end-of-life.
			Upgrade the site to PHP 8.3 or newer before general production use.
		</p>
	</div>
	<?php
}

if ( is_admin() ) {
	add_action( 'admin_notices', 'catora_service_visibility_legacy_php_notice' );
}
