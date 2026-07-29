<?php

defined( 'WP_UNINSTALL_PLUGIN' ) || exit;

delete_option( 'catora_service_visibility_settings' );
delete_option( 'catora_service_visibility_status' );
wp_clear_scheduled_hook( 'catora_service_visibility_sync' );
