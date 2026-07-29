# WordPress runtime hardening

This change set upgrades the optional WordPress bridge from package-only validation to clean-runtime acceptance.

The repository workflow installs the built ZIP on clean WordPress and MariaDB, exercises signed snapshots, forces one interrupted batch, verifies checkpointed resume, checks metadata extraction and default-disabled scheduling, and confirms uninstall cleanup.

The plugin now fails explicitly above the 10,000-record service-visibility contract limit instead of silently truncating, preserves temporary private batch checkpoints for retry, masks the saved token in WordPress Admin, requires HTTPS outside recognized local development hosts, and exports supported canonical, robots, authorship, featured-media and JSON-LD evidence.
