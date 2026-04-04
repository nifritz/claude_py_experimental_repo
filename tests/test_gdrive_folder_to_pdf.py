"""Tests for gdrive_folder_to_pdf.py (unit tests, no network calls)."""

import io
import pytest
import pypdf

from scripts.gdrive_folder_to_pdf import extract_folder_id, merge_pdfs


class TestExtractFolderId:
    def test_full_url(self):
        url = "https://drive.google.com/drive/folders/1ABC_xyz-123"
        assert extract_folder_id(url) == "1ABC_xyz-123"

    def test_url_with_query_params(self):
        url = "https://drive.google.com/drive/folders/1ABC_xyz-123?usp=sharing"
        assert extract_folder_id(url) == "1ABC_xyz-123"

    def test_plain_id(self):
        assert extract_folder_id("1ABC_xyz-123") == "1ABC_xyz-123"

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            extract_folder_id("https://example.com/not/a/drive/url")


class TestMergePdfs:
    def _make_pdf(self, text: str = "page") -> bytes:
        writer = pypdf.PdfWriter()
        writer.add_blank_page(width=200, height=200)
        buf = io.BytesIO()
        writer.write(buf)
        return buf.getvalue()

    def test_merge_two_pdfs(self):
        pdf1 = self._make_pdf()
        pdf2 = self._make_pdf()
        merged = merge_pdfs([pdf1, pdf2])
        reader = pypdf.PdfReader(io.BytesIO(merged))
        assert len(reader.pages) == 2

    def test_merge_single_pdf(self):
        pdf1 = self._make_pdf()
        merged = merge_pdfs([pdf1])
        reader = pypdf.PdfReader(io.BytesIO(merged))
        assert len(reader.pages) == 1
