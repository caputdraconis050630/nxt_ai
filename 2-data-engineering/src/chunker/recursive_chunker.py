import re
from typing import List, Sequence

PARAGRAPH_SPLIT_RE = re.compile(r"\n{2,}") # 문단 분할
SENTENCE_SPLIT_RE = re.compile(r"(?<=[\.!\?]|[。！？])\s+|(?<=\n)\s*") # 문장 분할

def split_paragraphs(text: str) -> List[str]:
    p = [p.strip() for p in PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    if p:
        return p
    return text.strip()

def split_sentences(text: str) -> List[str]:
    parts = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if parts:
        return parts
    return text.strip()






def recursive_chunk(text: str, chunk_size: int) -> List[str]:
    if not text:
        return []

    target_chars = chunk_size
    hard_max_chars = int(chunk_size * 1.5)

    chunks: List[str] = []
    paragraph_buffer: List[str] = []
    current_length = 0

    def flush(): 
        # paragraph buffer flush!
        nonlocal paragraph_buffer, current_length
        if not paragraph_buffer:
            return
        
        joined = "\n\n".join(paragraph_buffer)
        if len(joined) <= hard_max_chars:
            chunks.append(joined)  # hard_max_chars 보다 이하이므로 청크로 바로 추가
        else:
            # 너무 긴 문단 묶음은 문장 단위로 쪼개야한다
            for par in paragraph_buffer:
                if len(par) <= hard_max_chars:
                    chunks.append(par)
                else:
                    sentence_buffer: List[str] = []
                    sentence_length = 0
                    for s in split_sentences(par):
                        if sentence_length + len(s) + (1 if sentence_buffer else 0) > hard_max_chars:  # 문장 간 공백 1 주기
                            if sentence_buffer:
                                chunks.append(" ".join(sentence_buffer))
                            sentence_buffer = [s]
                            sentence_length = len(s)
                        else:
                            sentence_buffer.append(s)
                            sentence_length += len(s) + 1
                    if sentence_buffer:
                        chunks.append(" ".join(sentence_buffer))
        paragraph_buffer = []
        current_length = 0

    for par in split_paragraphs(text):
        paragraph_length = len(par)
        if current_length and current_length + 2 + paragraph_length > target_chars:
            flush()
            
        paragraph_buffer.append(par)
        current_length = len("\n\n".join(paragraph_buffer))

        if current_length > hard_max_chars:
            flush()

    flush()
    return chunks