<?php

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

$checkpoint = get_option( 'catora_service_visibility_checkpoint', array() );
$directory = is_array( $checkpoint ) && ! empty( $checkpoint['directory'] )
	? (string) $checkpoint['directory']
	: trailingslashit( get_temp_dir() ) . 'catora-service-visibility-' . substr( hash( 'sha256', ABSPATH ), 0, 16 );
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

delete_option( 'catora_service_visibility_settings' );
delete_option( 'catora_service_visibility_status' );
delete_option( 'catora_service_visibility_checkpoint' );
wp_clear_scheduled_hook( 'catora_service_visibility_sync' );
