import func_config
import upload_page


def _sample_cfg():
    return func_config.load_config(
        {
            "SEARCH_ENDPOINT": "https://srch-demo.search.windows.net",
            "STORAGE_BLOB_ENDPOINT": "https://stdemo.blob.core.windows.net",
            "SEARCH_INDEX_NAME": "demo-blob-index",
            "UPLOAD_CONTAINER": "pdfs",
        }
    )


def _sample_env():
    return {
        "WEBSITE_SITE_NAME": "blobsearch-demo",
        "WEBSITE_RESOURCE_GROUP": "rg-demo",
        "WEBSITE_OWNER_NAME": "sub-guid-1234+rg-demo-KoreaCentralwebspace-Linux",
    }


def test_validate_rejects_non_pdf():
    assert upload_page.validate_upload("a.txt", 10, 50) is not None


def test_validate_rejects_too_large():
    assert upload_page.validate_upload("a.pdf", 60 * 1024 * 1024, 50) is not None


def test_validate_rejects_empty_file_and_name():
    assert upload_page.validate_upload("a.pdf", 0, 50) is not None
    assert upload_page.validate_upload("", 10, 50) is not None


def test_validate_accepts_pdf_case_insensitive():
    assert upload_page.validate_upload("Report.PDF", 1234, 50) is None


def test_render_form_has_upload_controls():
    html = upload_page.render_form_html()
    assert "<form" in html
    assert 'type="file"' in html
    assert "/api/upload" in html
    assert 'method="post"' in html.lower()


def test_render_result_escapes_filename():
    html = upload_page.render_result_html("<script>.pdf")
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_render_error_escapes_message():
    html = upload_page.render_error_html("bad <x>")
    assert "<x>" not in html
    assert "&lt;x&gt;" in html


def test_build_resource_info_parses_names_and_subscription():
    info = upload_page.build_resource_info(_sample_cfg(), _sample_env())
    assert info.storage_account == "stdemo"
    assert info.search_service == "srch-demo"
    assert info.function_app == "blobsearch-demo"
    assert info.resource_group == "rg-demo"
    assert info.subscription_id == "sub-guid-1234"
    assert info.upload_container == "pdfs"
    assert info.search_index == "demo-blob-index"
    assert info.event_subscription == "blob-to-search-demo"
    assert "portal.azure.com" in info.storage_url
    assert "Microsoft.Storage/storageAccounts/stdemo" in info.storage_url
    assert "Microsoft.Search/searchServices/srch-demo" in info.search_url
    assert "Microsoft.Web/sites/blobsearch-demo" in info.function_url


def test_build_resource_info_without_platform_env_has_no_urls():
    info = upload_page.build_resource_info(_sample_cfg(), {})
    assert info.storage_account == "stdemo"
    assert info.subscription_id == ""
    assert info.storage_url == ""
    assert info.function_url == ""


def test_render_form_includes_architecture_diagram():
    html = upload_page.render_form_html()
    assert "<svg" in html
    assert "Event Grid" in html
    assert "AI Search" in html


def test_render_form_includes_portal_paths_when_info_given():
    info = upload_page.build_resource_info(_sample_cfg(), _sample_env())
    html = upload_page.render_form_html(info)
    assert "portal.azure.com" in html
    assert "stdemo" in html
    assert "srch-demo" in html
    assert "blobsearch-demo" in html
    assert "rg-demo" in html
    assert "blob-to-search-demo" in html
    assert "demo-blob-index" in html
    assert "pdfs" in html


def test_render_form_escapes_resource_names():
    cfg = func_config.load_config(
        {"STORAGE_BLOB_ENDPOINT": "https://stdemo.blob.core.windows.net"}
    )
    info = upload_page.build_resource_info(cfg, {"WEBSITE_SITE_NAME": "<script>"})
    html = upload_page.render_form_html(info)
    assert "<script>" not in html


def test_build_resource_info_includes_config_detail():
    info = upload_page.build_resource_info(_sample_cfg(), _sample_env())
    assert info.chunk_size == 1000
    assert info.max_upload_mb == 50


def test_render_form_includes_config_summary_when_info_given():
    info = upload_page.build_resource_info(_sample_cfg(), _sample_env())
    html = upload_page.render_form_html(info)
    # compact "주요 설정" essentials
    assert "주요 설정" in html
    assert "demo-blob-index" in html
    assert "pdfs" in html
    assert ">1000<" in html  # chunk size value rendered
    assert ">50<" in html  # max upload MB value rendered
    assert "임베딩 없이 정적 분할" in html
    assert "BlobCreated" in html
    assert "키리스" in html
    # verbose detail intentionally dropped
    assert "인덱스 스키마" not in html
    assert "Search Index Data Contributor" not in html
    assert "Edm.String" not in html


def test_render_form_omits_config_summary_without_info():
    html = upload_page.render_form_html()
    assert "주요 설정" not in html
    assert "키리스" not in html
