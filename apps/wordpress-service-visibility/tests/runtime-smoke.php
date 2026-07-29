<?php

function catora_assert( bool $condition, string $message ): void {
	if ( ! $condition ) {
		fwrite( STDERR, $message . PHP_EOL );
		exit( 1 );
	}
}

$service = Catora_Service_Visibility::instance();
$settings = get_option( 'catora_service_visibility_settings', array() );
catora_assert( is_array( $settings ), 'Plugin settings were not stored.' );
catora_assert( 'runtime-secret' === ( $settings['token'] ?? null ), 'Runtime token is missing.' );

$sanitized = $service->sanitize_settings(
	array(
		'endpoint'  => 'http://host.docker.internal:8787',
		'source_id' => '11111111-1111-4111-8111-111111111111',
		'token'     => '',
	)
);
catora_assert( 'runtime-secret' === ( $sanitized['token'] ?? null ), 'Blank token submission did not preserve the configured secret.' );
catora_assert( false === wp_next_scheduled( 'catora_service_visibility_sync' ), 'Scheduled snapshots were enabled without opt-in.' );

$service->sync();
$first_status = get_option( 'catora_service_visibility_status', array() );
$checkpoint = get_option( 'catora_service_visibility_checkpoint', array() );
catora_assert( 'Failed' === ( $first_status['status'] ?? null ), 'The intentional interruption did not surface as a failed snapshot.' );
catora_assert( is_array( $checkpoint ) && 1 === (int) ( $checkpoint['accepted_batches'] ?? -1 ), 'The accepted batch checkpoint was not persisted.' );

$service->sync();
$second_status = get_option( 'catora_service_visibility_status', array() );
catora_assert( 'Healthy' === ( $second_status['status'] ?? null ), 'The interrupted snapshot did not resume successfully.' );
catora_assert( false === get_option( 'catora_service_visibility_checkpoint', false ), 'The completed snapshot checkpoint was not removed.' );
catora_assert( false === wp_next_scheduled( 'catora_service_visibility_sync' ), 'Manual snapshot unexpectedly enabled scheduling.' );
