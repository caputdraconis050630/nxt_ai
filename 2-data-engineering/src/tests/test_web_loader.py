import pytest
from src.loader.webbase_loader import load_web, WebLoadResult

def test_web_loader_basic():
    url = "https://python.org/"
    res = load_web(url)
    assert isinstance(res, WebLoadResult)
    assert res.url == url
    assert isinstance(res.html_raw, str) and len(res.html_raw) > 0
    assert isinstance(res.text_raw, str)
    assert hasattr(res, "title")
    assert isinstance(res.image_urls, list)

def test_web_loader_timeout():
    with pytest.raises(Exception):
        load_web("https://이세상에없는.site")