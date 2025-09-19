import math
import re
from typing import List, Optional
from langchain_core.embeddings import Embeddings

SENT_SPLIT = re.compile(r"(?<=[\.!\?]|[。！？])\s+|(?<=\n)\s*")
threshold = 0.7

def split_text_to_sentences(text: str) -> List[str]:
    parts = []
    for s in SENT_SPLIT.split(text):
        if s.strip():
            parts.append(s.strip())
    
    if len(parts) == 0:
        return [text.strip()]
    else:
        return parts

def cosine_sim(vec1, vec2):
    dot = 0
    for i in range(len(vec1)):
        dot += vec1[i] * vec2[i]
    
    norm1 = 0
    norm2 = 0
    for v in vec1:
        norm1 += v * v
    for v in vec2:
        norm2 += v * v
    
    norm1 = math.sqrt(norm1)
    norm2 = math.sqrt(norm2)
    
    if norm1 == 0 or norm2 == 0:
        return 0
    
    return dot / (norm1 * norm2)



def semantic_chunk(text: str, target_chars: int, embedder: Embeddings) -> List[str]:
    if not text:
        return []

    sentences = split_text_to_sentences(text)
    if not sentences:
        return []

    if len(sentences) == 1:
        return [text]

    chunks: List[str] = []
    current_chunk_sentences: List[str] = [sentences[0]]
    current_chunk_embedding: Optional[List[float]] = None

    for i in range(1, len(sentences)):
        sentence = sentences[i]
        
        if current_chunk_embedding is None:
            current_chunk_text = ' '.join(current_chunk_sentences)
            current_chunk_embedding = embedder.embed_query(current_chunk_text)
        
        sentence_embedding = embedder.embed_query(sentence)
        
        similarity = cosine_sim(current_chunk_embedding, sentence_embedding)
        
        current_length = sum(len(s) for s in current_chunk_sentences)
        
        if similarity < threshold or current_length + len(sentence) > target_chars:
            chunks.append(' '.join(current_chunk_sentences))
            
            current_chunk_sentences = [sentence]
            current_chunk_embedding = None
        else:
            current_chunk_sentences.append(sentence)
            current_chunk_embedding = None
    if current_chunk_sentences:
        chunks.append(' '.join(current_chunk_sentences))

    return chunks