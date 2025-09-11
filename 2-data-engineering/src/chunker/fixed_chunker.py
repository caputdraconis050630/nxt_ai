from typing import List

def fixed_chunk(text: str, max_chars: int, overlap: int) -> List[str]:
    if not text:
        return []

    chunks: List[str] = []
    length = len(text)
    start = 0 # 현재 인덱스
    while start < length:
        end = min(start + max_chars, length)
        chunks.append(text[start:end])

        if end == length:
            break
        start = end - overlap
    return chunks