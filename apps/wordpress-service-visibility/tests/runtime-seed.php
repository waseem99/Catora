<?php

foreach ( get_posts( array( 'post_type' => array( 'post', 'page' ), 'post_status' => 'any', 'numberposts' => -1 ) ) as $existing ) {
	wp_delete_post( $existing->ID, true );
}

for ( $index = 0; $index < 55; $index++ ) {
	$schema = 0 === $index
		? '<script type="application/ld+json">{"@context":"https://schema.org","@type":"Service","name":"Runtime Service"}</script>'
		: '';
	$post_id = wp_insert_post(
		array(
			'post_type'    => 0 === $index % 2 ? 'page' : 'post',
			'post_status'  => 'publish',
			'post_title'   => 'Runtime Service ' . $index,
			'post_content' => '<h1>Runtime Service ' . $index . '</h1><h2>Evidence</h2><p>Public service evidence for runtime record ' . $index . '.</p><a href="https://wp.example.test/contact">Contact</a>' . $schema,
			'post_excerpt' => 'Runtime service description ' . $index,
		),
		true
	);
	if ( is_wp_error( $post_id ) ) {
		fwrite( STDERR, $post_id->get_error_message() . PHP_EOL );
		exit( 1 );
	}
	if ( 0 === $index ) {
		update_post_meta( $post_id, '_yoast_wpseo_metadesc', 'Runtime Yoast description' );
		update_post_meta( $post_id, '_yoast_wpseo_canonical', 'https://wp.example.test/canonical/runtime-service' );
		update_post_meta( $post_id, '_yoast_wpseo_meta-robots-noindex', '1' );
	}
}

update_option(
	'catora_service_visibility_settings',
	array(
		'endpoint'              => 'http://host.docker.internal:8787',
		'source_id'             => '11111111-1111-4111-8111-111111111111',
		'token'                 => 'runtime-secret',
		'enable_scheduled_sync' => false,
		'enable_drafts'         => false,
	),
	false
);
