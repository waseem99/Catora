<?php

defined('WP_UNINSTALL_PLUGIN') || exit;

delete_option('catora_sv_endpoint');
delete_option('catora_sv_token');
delete_option('catora_sv_last_sync');
delete_option('catora_sv_last_error');
delete_option('catora_sv_scheduled_enabled');

wp_clear_scheduled_hook('catora_sv_scheduled_sync');
delete_transient('catora_sv_sync_lock');
