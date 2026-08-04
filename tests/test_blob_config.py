import func_config


def test_load_config_defaults():
    c = func_config.load_config({})
    assert c.index_name == "demo-blob-index"
    assert c.upload_container == "pdfs"
    assert c.chunk_size == 1000
    assert c.max_upload_mb == 50
    assert c.search_endpoint == ""


def test_load_config_overrides():
    c = func_config.load_config(
        {"CHUNK_SIZE": "500", "SEARCH_ENDPOINT": "https://s", "MAX_UPLOAD_MB": "10"}
    )
    assert c.chunk_size == 500
    assert c.search_endpoint == "https://s"
    assert c.max_upload_mb == 10
