import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, urljoin
from bs4 import BeautifulSoup
import requests

@dataclass
class WebLoadResult:
    url: str
    title: str
    html_raw: str
    text_raw: str
    image_urls: List[str]
    meta: Dict[str, Any]

def fetch_html(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        encoding = response.apparent_encoding
        if encoding is None:
            encoding = 'utf-8'
        response.encoding = encoding
        result = response.text
        return result
    except Exception as e:
        error_msg = "웹페이지 로딩 실패: " + url + " - " + str(e)
        raise Exception(error_msg)

def extract_title(html):
    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.title
    title = None
    if title_tag:
        title = title_tag.string
    else:
        title = None
    return title

def extract_text(html):
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text()
    return text_content

def extract_img_src(html):
    soup = BeautifulSoup(html, "html.parser")
    img_tags = soup.find_all("img")
    img_srcs = []
    for img in img_tags:
        src = img["src"]
        img_srcs.append(src)
    return img_srcs


def load_web(url):
    html = ""
    try:
        html = fetch_html(url)
    except Exception as e:
        error_str = str(e)
        error_msg = "웹페이지 로딩 실패: " + url + " - " + error_str
        raise Exception(error_msg)

    title = extract_title(html)
    text = extract_text(html)
    img_srcs = extract_img_src(html)

    html_length = len(html)
    text_length = len(text)
    img_srcs_length = len(img_srcs)

    meta_dict = {}
    meta_dict["source"] = url
    meta_dict["length_html"] = html_length
    meta_dict["length_text"] = text_length
    meta_dict["length_img_srcs"] = img_srcs_length

    result = WebLoadResult(
        url = url,
        title = title,
        html_raw = html,
        text_raw = text,
        image_urls = img_srcs,
        meta = meta_dict
    )
    return result
    



