# 오지라퍼 Streamlit

## 실행 방법

```bash
# 가상환경 생성
uv venv --python 3.12

# 가상환경 활성화
source .venv/bin/activate

# 의존성 설치
uv sync

# 환경 변수 설정
cp .env.example .env

# Streamlit 앱 실행
python -m streamlit run app/main.py
```

## 환경 변수

다음 환경 변수들을 `.env` 파일에 설정해야 합니다:

- `BEDROCK_KB_ID`: Bedrock Knowledge Base ID
- `BEDROCK_MODEL_ID`: 사용할 Bedrock 모델 ID (예: apac.amazon.nova-micro-v1:0)
- `AWS_REGION`: AWS 리전
- `SLACK_CHANNEL_ID`: Slack 채널 ID
- `SLACK_WORKSPACE`: Slack 워크스페이스 호스트
