from src.auditmcp import _normalize_concept, _to_underscore_form

def test_colon_form_stays_colon():
    assert _normalize_concept("us-gaap:AssetsCurrent") == "us-gaap:AssetsCurrent"

def test_underscore_form_becomes_colon():
    assert _normalize_concept("us-gaap_AssetsCurrent") == "us-gaap:AssetsCurrent"

def test_already_bare_local_name_is_unchanged():
    assert _normalize_concept("AssetsCurrent") == "AssetsCurrent"

def test_to_underscore_form():
    assert _to_underscore_form("us-gaap:AssetsCurrent") == "us-gaap_AssetsCurrent"
    assert _to_underscore_form("us-gaap_AssetsCurrent") == "us-gaap_AssetsCurrent"

def test_invalid_prefix_characters_leave_string_unchanged():
    # Prefix contains '!' which is not alnum/hyphen → not a valid QName prefix.
    assert _normalize_concept("us!gaap_AssetsCurrent") == "us!gaap_AssetsCurrent"

def test_leading_underscore_is_unchanged():
    # No prefix before the first underscore (idx <= 0 branch).
    assert _normalize_concept("_Assets") == "_Assets"
