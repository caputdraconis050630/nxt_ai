import hashlib
import re
from langchain_core.documents import Document


class DocumentStructurer:
    def _generate_doc_id(self, source_url, chunk_index=0):
        content = source_url + "#" + str(chunk_index)
        return hashlib.md5(content.encode()).hexdigest()

    def _extract_keywords(self, text, max_keywords=10):
        words = re.findall(r'[가-힣a-zA-Z0-9]+', text.lower()) # 한글, 영어, 숫자 추출
        
        stopwords = {'의', '가', '이', '을', '를', '에', '와', '과', '으로', '로', 'and', 'or', 'the', 'a', 'an', 'in', 'on', 'at', 'to', 'for'} # 불용어
        
        filtered_words = []
        for w in words:
            if w not in stopwords and len(w) > 1:
                filtered_words.append(w)
        
        word_freq = {} # 단어 빈도수
        for word in filtered_words:
            if word in word_freq:
                word_freq[word] = word_freq[word] + 1
            else:
                word_freq[word] = 1
        
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True) # 빈도수 내림차순 정렬
        result = []
        for word, freq in sorted_words[:max_keywords]:
            result.append(word)
        return result

    def structure_document(self, content, source_url, source_type, chunk_index, metadata=None):
        meta = {} # 메타데이터
        if metadata is not None:
            meta = metadata.copy()
        else:
            meta = {}
        
        meta["id"] = self._generate_doc_id(source_url, chunk_index)
        meta["source_type"] = source_type
        meta["source_url"] = source_url
        meta["keywords"] = self._extract_keywords(content)
        meta["chunk_index"] = chunk_index
        
        return Document(page_content=content, metadata=meta)
