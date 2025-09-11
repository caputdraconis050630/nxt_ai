import os
import pytest
from src.loader.pdf_loader import load_pdf, PDFLoadResult

path = os.path.dirname(os.path.abspath(__file__))
SAMPLE_PDF = os.path.join(path, "../../data/ai과제.pdf")

@pytest.mark.skipif(not os.path.exists(SAMPLE_PDF), reason="샘플 PDF 없음")
def test_pdf_loader_basic():
    res = load_pdf(SAMPLE_PDF, max_pages=1)
    assert isinstance(res, PDFLoadResult)
    assert res.total_pages >= 1
    assert len(res.pages) == 1
    p0 = res.pages[0]
    assert p0.page == 1
    assert isinstance(p0.content, str)
    assert "source" in p0.meta and "page" in p0.meta and "total_pages" in p0.meta

def test_pdf_loader_not_found():
    with pytest.raises(FileNotFoundError):
        load_pdf("그런/파일/없음.pdf")