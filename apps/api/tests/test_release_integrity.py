from catora_api.release_integrity import validate_release_integrity


def test_release_integrity_contract() -> None:
    result = validate_release_integrity()
    assert result["schema_head"] == "0024"
    assert result["checked_tables"] == 8
    assert result["checked_routes"] == 9
    assert result["checked_settings"] == 2
