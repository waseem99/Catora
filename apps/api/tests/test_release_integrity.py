from catora_api.release_integrity import validate_release_integrity


def test_release_integrity_contract() -> None:
    result = validate_release_integrity()
    assert result["schema_head"] == "0027"
    assert result["checked_tables"] == 25
    assert result["checked_routes"] == 37
    assert result["checked_settings"] == 6
