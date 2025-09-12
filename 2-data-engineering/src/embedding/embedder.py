import boto3
import json
from typing import List, Optional
import os

class BedrockEmbedder: # AWS Bedrock Titan Text Embeddings V2 모델 기반 텍스트 임베딩을 생성하는 클래스
    def __init__(self):
        self.model_id = os.getenv("BEDROCK_EMBEDDING_MODEL_ID")
        self.region = os.getenv("AWS_REGION")
        self.session = boto3.Session()
            
        self.bedrock_runtime = self.session.client(
            service_name='bedrock-runtime',
            region_name=self.region
        )
        print(f"BedrockEmbedder 초기화 성공")

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        embeddings = []
        for i, text in enumerate(texts):
            print(f"   {i+1}/{len(texts)} 청크 임베딩 중...")
            embedding = self.embed_text(text)
            if embedding:
                embeddings.append(embedding)
        return embeddings

    def embed_text(self, text: str) -> Optional[List[float]]:
        if not text.strip():
            print("빈 텍스트 들어왔음")
            return None
        
        try:
            body = json.dumps({
                "inputText": text
            })
            
            response = self.bedrock_runtime.invoke_model(
                body=body,
                modelId=self.model_id,
                accept="application/json",
                contentType="application/json",
            )
            
            response_body = json.loads(response["body"].read())
            return response_body.get("embedding")
            
        except Exception as e:
            print(f"임베딩 실패: '{text}'. error: {e}")
            return None

