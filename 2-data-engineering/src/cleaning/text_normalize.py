import re
from collections import Counter
from typing import Iterable, List
from bs4 import BeautifulSoup

def normalize_whitespace(text):
    result = text
    result = result.replace("\r\n", "\n")
    result = result.replace("\r", "\n")
    result = result.replace("\t", " ")
    result = re.sub(r"[ \u00A0]+", " ", result)    # 다중 공백 → 1
    result = re.sub(r"\n{3,}", "\n\n", result)     # 빈 줄 3개 이상이면? → 2
    final_result = result.strip()
    return final_result

def drop_short_noise_lines(lines):
    result = []
    for ln in lines:
        stripped = ln.strip()
        if len(stripped) >= 2:
            result.append(ln)
    return result


def strip_repeating_headers_footers(pages, top_n=2, bottom_n=2):
    def head_tail(lines):
        head = lines[:top_n]
        tail = []
        if bottom_n > 0:
            tail = lines[-bottom_n:]
        combined = head + tail
        result = []
        for s in combined:
            stripped = s.strip()
            if stripped:
                result.append(stripped)
        return result

    candidates = Counter()
    split_pages = []
    for p in pages:
        split_pages.append(p.splitlines())
    
    for lines in split_pages:
        head_tail_result = head_tail(lines)
        candidates.update(head_tail_result)

    pages_len = len(pages)
    half_pages = pages_len // 2
    threshold = max(2, half_pages)
    
    blacklist = set()
    for s, c in candidates.items():
        if c >= threshold:
            blacklist.add(s)

    cleaned_pages = []
    for lines in split_pages:
        kept = []
        for ln in lines:
            ln_stripped = ln.strip()
            if ln_stripped not in blacklist:
                kept.append(ln)
        joined = "\n".join(kept)
        cleaned_pages.append(joined)
    return cleaned_pages


def pdf_to_plain(page_texts):
    pages = []
    for p in page_texts:
        normalized = normalize_whitespace(p)
        pages.append(normalized)
    
    pages = strip_repeating_headers_footers(pages)
    joined = "\n\n".join(pages)
    split_lines = joined.splitlines()
    lines = drop_short_noise_lines(split_lines)
    final_result = "\n".join(lines)
    return final_result

def web_to_plain(html_or_text):
    # HTML처럼 보이면 soup로 파싱해서 텍스트만 추출
    has_lt = "<" in html_or_text
    has_gt = ">" in html_or_text
    text = ""
    
    if has_lt and has_gt: # html 특
        soup = BeautifulSoup(html_or_text, "html.parser")
        
        tags_to_remove = ["script", "style", "noscript"]
        for tag in soup(tags_to_remove): # script/style 제거
            tag.decompose()
        text = soup.get_text(separator="\n")
    else:
        text = html_or_text

    text = normalize_whitespace(text)
    text = re.sub(r"\s{2,}", " ", text)
    stripped_text = text.strip()
    return stripped_text