from langchain_aws import BedrockEmbeddings
from langchain_community.vectorstores import OpenSearchVectorSearch
from ..loader.pdf_loader import load_pdf
from ..loader.webbase_loader import load_web
from ..chunker.semantic_chunker import semantic_chunk
from ..chunker.fixed_chunker import fixed_chunk
from ..chunker.recursive_chunker import recursive_chunk
from ..cleaning.text_normalize import pdf_to_plain, web_to_plain
from ..cleaning.table_to_markdown import pdf_text_to_markdown
from ..structuring.structurer import DocumentStructurer
from langchain_core.documents import Document
from opensearchpy import AWSV4SignerAuth, RequestsHttpConnection
import boto3
import os
from typing import Optional, List, Dict, Any

class Pipeline:
    def __init__(self, embeddings: BedrockEmbeddings, index_name: str):
        self.embeddings = embeddings
        self.index_name = index_name
        self.structurer = DocumentStructurer()

        credentials = boto3.Session().get_credentials()
        auth = AWSV4SignerAuth(credentials, os.getenv("AWS_REGION"), "aoss")
        self.vector_store = OpenSearchVectorSearch(
            opensearch_url = os.getenv("OPENSEARCH_ENDPOINT"),
            index_name = self.index_name,
            embedding_function = self.embeddings,
            is_aoss = True,
            embedding_dimension = 1024,
            http_auth = auth,
            connection_class = RequestsHttpConnection,
            use_ssl = True,
            verify_certs = True,
            vector_field = "vector_field",
            text_field = "text",
            # 참고 https://docs.aws.amazon.com/ko_kr/opensearch-service/latest/developerguide/serverless-sdk.html
            # 참고 https://github.com/langchain-ai/langchain/discussions/17360
        )
        
        # self.vector_store = OpenSearch(
        #     hosts=[os.getenv("OPENSEARCH_ENDPOINT")],
        #     http_auth=auth,
        #     use_ssl=True,
        #     verify_certs=True,
        #     connection_class=RequestsHttpConnection
        # )
        print("Pipeline 초기화 성공")

    def run(self, source: str, chunker: str, chunk_size: int, chunk_overlap: int):
        is_pdf = source.endswith(".pdf")

        # Loader로 로드하고 Cleaning
        cleaned: List[Dict[str, Any]] = []
        if is_pdf:
            pdf = load_pdf(source)
            for p in pdf.pages:
                plain = pdf_to_plain([p.content])
                tables = pdf_text_to_markdown(plain)
                if tables:
                    plain = plain + "\n\n" + "\n\n".join(tables)
                cleaned.append({
                    "page_content": plain,
                    "metadata": {
                        "source": pdf.source,
                        "page_number": p.page,
                        "total_pages": pdf.total_pages,
                    }
                })
        else:
            web = load_web(source)
            plain = web_to_plain(web.text_raw)
            meta_data = {"source": web.url, "title": web.title}
            for key in web.meta:
                meta_data[key] = web.meta[key]
            cleaned.append({
                "page_content": plain,
                "metadata": meta_data
            })

        content_list = []
        for c in cleaned:
            content_list.append(c["page_content"])
        merged_content = "\n\n".join(content_list)

        # Chunker로 청크
        if chunker == "semantic":
            chunks = semantic_chunk(
                text=merged_content,
                target_chars=chunk_size,
                embedder=self.embeddings
            )
        elif chunker == "fixed":
            chunks = fixed_chunk(merged_content, max_chars=chunk_size, overlap=chunk_overlap)
        elif chunker == "recursive":
            chunks = recursive_chunk(merged_content, chunk_size=chunk_size)
        else:
            chunks = [merged_content]

        structured_docs = []
        i = 0
        for chunk in chunks:
            opensearch_doc = self.structurer.structure_document(
                content=chunk,
                source_url=source,
                source_type="pdf" if is_pdf else "web",
                chunk_index=i,
                metadata={}
            )
            structured_docs.append(opensearch_doc)
            i = i + 1

        self.vector_store.add_documents(structured_docs)

        result_list = []
        for doc in structured_docs:
            content = doc.page_content
            if len(content) > 200:
                content = content[:200] + "..."
            
            result_list.append({
                "id": doc.metadata.get("id"),
                "content": content,
                "keywords": doc.metadata.get("keywords", []),
                "chunk_index": doc.metadata.get("chunk_index"),
                "source_type": doc.metadata.get("source_type"),
                "metadata": doc.metadata,
            })
        return result_list
        

        

    def search(self, query: str, k: int, text_weight: float, vector_weight: float) -> List[Dict[str, Any]]:
        vec_results = self.vector_store.similarity_search_with_score(query, k=k)

        text_results = []
        client = getattr(self.vector_store, "client", None)
        if client is not None:
            body = {
                "query": {
                    "multi_match": {
                        "query": query,
                        "fields": ["text^2", "metadata.title^3", "metadata.keywords^4", "metadata.summary^2"],
                        "type": "best_fields",
                        "fuzziness": "AUTO",
                    }
                },
                "size": k,
                "_source": True,
            }
            resp = client.search(index=self.index_name, body=body)
            hits = resp.get("hits", {}).get("hits", [])
            for h in hits:
                src = h.get("_source", {})
                page = src.get("text", "")
                meta = src.get("metadata", {}) or {}
                text_results.append((Document(page_content=page, metadata=meta), float(h.get("_score", 0.0))))

        # 정규화 및 결합
        def normalize(scores: List[float]) -> List[float]:
            if not scores:
                return []
            m = max(scores) or 1.0
            return [s / m for s in scores]

        vec_scores = normalize([s for _, s in vec_results])
        txt_scores = normalize([s for _, s in text_results])

        combined = {}

        for (doc, s), ns in zip(vec_results, vec_scores):
            key = str(doc.metadata.get("id") or hash(doc.page_content))
            combined[key] = {"doc": doc, "v": ns, "t": 0.0}

        for (doc, s), ns in zip(text_results, txt_scores):
            key = str(doc.metadata.get("id") or hash(doc.page_content))
            if key in combined:
                combined[key]["t"] = ns
            else:
                combined[key] = {"doc": doc, "v": 0.0, "t": ns}

        items = []
        for key, entry in combined.items():
            score = vector_weight * entry["v"] + text_weight * entry["t"]
            d = entry["doc"]
            items.append((score, d, entry["v"], entry["t"]))

        items.sort(key=lambda x: x[0], reverse=True)
        items = items[:k]

        result_list = []
        for score, d, vec_score, txt_score in items:
            result_list.append({
                "score": score,
                "vector_score": vec_score,
                "text_score": txt_score,
                "vector_weight": vector_weight,
                "text_weight": text_weight,
                "page_content": d.page_content,
                "metadata": d.metadata,
            })
        return result_list
    
    def reset_index(self):
        # https://python.langchain.com/api_reference/community/vectorstores/langchain_community.vectorstores.opensearch_vector_search.OpenSearchVectorSearch.html
        client = self.vector_store.client
        idx = self.index_name
        if not self.vector_store.index_exists():
            return False

        ids = []
        cursor = None
        size = 1000
        while True:
            body = {
                "size": size,
                "query": {"match_all": {}},
                "sort": [{"_id": "asc"}],
                "_source": False,
            }
            if cursor is not None:
                body["search_after"] = cursor

            resp = client.search(index=idx, body=body)
            hits = resp.get("hits", {}).get("hits", [])
            if not hits:
                break

            for h in hits:
                ids.append(h["_id"])
            cursor = hits[-1]["sort"]

        B = 1000
        i = 0
        while i < len(ids):
            batch_ids = ids[i:i+B]
            self.vector_store.delete(ids=batch_ids, refresh_indices=False)
            i = i + B
        return True


def get_pipeline() -> Optional[Pipeline]:
    # 환경 변수 확인
    opensearch_endpoint = os.getenv("OPENSEARCH_ENDPOINT")
    index_name = os.getenv("OPENSEARCH_INDEX_NAME")
    
    embeddings = BedrockEmbeddings(
        model_id=os.getenv("BEDROCK_EMBEDDING_MODEL_ID"),
        region_name=os.getenv("AWS_REGION")
    )

    return Pipeline(
        embeddings=embeddings,
        index_name=index_name
    )