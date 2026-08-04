import upload_page


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
