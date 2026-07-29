<?php
/**
 * Plugin Name: Catora Service Visibility
 * Plugin URI: https://github.com/waseem99/Catora
 * Description: Sends approved public WordPress content to Catora for evidence-backed SEO, AEO, and AI-discovery audits. Approved fixes are created as drafts only.
 * Version: 0.2.1
 * Requires at least: 6.4
 * Requires PHP: 8.1
 * Author: Catora
 * Author URI: https://github.com/waseem99/Catora
 * License: Proprietary
 */

defined( 'ABSPATH' ) || exit;

define( 'CATORA_SERVICE_VISIBILITY_VERSION', '0.2.1' );
define( 'CATORA_SERVICE_VISIBILITY_FILE', __FILE__ );
define( 'CATORA_SERVICE_VISIBILITY_DIR', plugin_dir_path( __FILE__ ) );

require_once CATORA_SERVICE_VISIBILITY_DIR . 'includes/class-catora-service-visibility.php';

register_activation_hook( __FILE__, array( 'Catora_Service_Visibility', 'activate' ) );
register_deactivation_hook( __FILE__, array( 'Catora_Service_Visibility', 'deactivate' ) );

Catora_Service_Visibility::instance();
