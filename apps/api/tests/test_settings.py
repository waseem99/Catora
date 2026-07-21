import pytest

from catora_api.config import Settings


def test_production_rejects_default_object_storage_secret() -> None:
    settings = Settings(environment="production", s3_secret_key="change-me-in-production")
    with pytest.raises(ValueError, match="production secret"):
        settings.validate_production()


def test_development_allows_local_defaults() -> None:
    Settings(environment="development").validate_production()
