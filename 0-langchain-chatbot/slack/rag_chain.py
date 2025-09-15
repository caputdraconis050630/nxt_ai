import os
import json
import logging
import requests
import asyncio
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from langchain_aws import AmazonKnowledgeBasesRetriever
from langchain_aws.chat_models import ChatBedrock
from langchain_core.runnables import RunnableParallel, RunnableLambda
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

logger = logging.getLogger()
logger.setLevel(logging.INFO)


BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID")
MCP_SERVER_ENDPOINT = os.getenv("MCP_SERVER_ENDPOINT")
SLACK_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID") # 테스트 채널 사용할 때를 위해 따로 설정
SLACK_999_CHANNEL_ID = os.getenv("SLACK_999_CHANNEL_ID")
SLACK_WORKSPACE = os.getenv("SLACK_WORKSPACE")
SLACK_RELEVANCE_THRESHOLD = 0.3 # 슬랙 컨텍스트 관련성 임계값

slack_client = WebClient(token=SLACK_TOKEN)

prompt = ChatPromptTemplate.from_messages([
    ("system",
    "너의 이름은 '오지라퍼'야. 너에게 물어보지는 않았지만, 다른 사람이 답하기 전에 먼저 오지랖을 부려 답변하는 상황이야. "
    "너가 할 일은 사용자의 질문에 친절하게 근거와 함께 답변하는거야. "
    "아래 두개의 컨텍스트(Slack Knowledge Base, AWS Docs)를 참고하여 한국어로 정확하고 간결하게 답변해줘. "
    "본문에는 출처 표기하지 말아줘. 아래에 따로 첨부할거야. "
    "근거 혹은 질문이 부정확하다면, 추가 정보가 필요하다고 말해줘"),
    ("human",
    "질문: {question}\n\n"
    "[슬랙 스레드 컨텍스트]\n{kb_context}\n\n"
    "[AWS 공식문서 컨텍스트]\n{mcp_context}\n\n"
    "응답:")
])
summary_prompt = ChatPromptTemplate.from_messages([
    ("system", "사용자의 질문을 검색에 최적화된 형태로 요약해줘. 문장 형태가 아닌, 핵심 키워드와 개념만으로 요약해줘."),
    ("human", "질문: {question}\n\n검색용 요약:")
])

retriever = AmazonKnowledgeBasesRetriever(
    knowledge_base_id=BEDROCK_KB_ID,
    region_name="ap-northeast-2",
    retrieval_config={"vectorSearchConfiguration": {"numberOfResults": 3, "overrideSearchType": "HYBRID"}},
)
llm = ChatBedrock(model_id=BEDROCK_MODEL_ID, region_name="ap-northeast-2")

def mcp_fetch_from_fargate(question: str):
    if not MCP_SERVER_ENDPOINT:
        logger.warning("MCP_SERVER_ENDPOINT 값이 설정되지 않았습니다.")
        return []

    base = MCP_SERVER_ENDPOINT.rstrip("/")
    sse_url = f"{base}/sse"

    async def _run():
        client = MultiServerMCPClient({
            "aws-documentation-mcp-server": {
                "transport": "sse",
                "url": sse_url,
            }
        })

        async with client.session("aws-documentation-mcp-server") as session:
            tools = await load_mcp_tools(session)

            search_tool = next((t for t in tools if t.name == "search_documentation"), None)
            read_tool = next((t for t in tools if t.name == "read_documentation"), None)

            if not search_tool:
                logger.warning("search_documentation 없다")
                return []
            try:
                search_results = await asyncio.wait_for(
                    search_tool.ainvoke({"search_phrase": question, "limit": 5}),
                    timeout=8.0
                )
            except Exception as e:
                logger.error(f"MCP 검색 실패: {e}")
                return []

            docs = []
            if isinstance(search_results, list):
                for item in search_results[:3]:
                    try:
                        if isinstance(item, str):
                            item = json.loads(item)

                        url = item.get("url", "")
                        title = item.get("title", "AWS Doc")
                        context = item.get("context", "")

                        content = context
                        if url and read_tool:
                            try:
                                doc = await asyncio.wait_for(
                                    read_tool.ainvoke({"url": url}),
                                    timeout=8.0
                                )
                                content = doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False)
                            except Exception as read_err:
                                logger.warning(f"문서 읽기 실패({url}): {read_err} → context 사용")

                        if isinstance(content, str):
                            content = content[:1500]

                        docs.append({"title": title, "url": url, "content": content})
                    except Exception as parse_err:
                        logger.warning(f"검색 결과 파싱 실패: {parse_err}")
                        continue

            return docs

    try:
        return asyncio.run(_run())
    except RuntimeError:
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_run())

def knowledge_base_fetch(q: str):
    return retriever.invoke(q)

def slack_link_from_s3_uri(s3_uri: str, channel_id: str, workspace_host: str) -> str:
    filename = os.path.basename(s3_uri.split("/", 3)[-1])
    ts = os.path.splitext(filename)[0].replace(".", "")
    return f"https://{workspace_host}/archives/{channel_id}/p{ts}"

def knowledge_base_format(threads):
    if not threads:
        return "KB 컨텍스트 없음", []
    
    blocks, sources = [], []
    for d in threads:
        score = d.metadata.get('score', 0.0)
        if score < SLACK_RELEVANCE_THRESHOLD:
            continue
        
        meta = d.metadata or {}
        loc = meta.get("location", {})
        s3u = loc.get("s3Location", {}).get("uri", "")
        link = slack_link_from_s3_uri(s3u, SLACK_999_CHANNEL_ID, SLACK_WORKSPACE)
        
        blocks.append(f"[KB] {s3u}\n{d.page_content}")
        sources.append({"s3": s3u, "slack": link})
        
    if not blocks:
        return "의미있는 KB 결과가 없습니다", []
    return "\n\n---\n\n".join(blocks), sources

def mcp_format(docs: list[dict]):
    if not docs:
        return "MCP 컨텍스트 없음", []
    
    blocks, sources_with_titles = [], []
    for d in docs:
        title = d.get("title", "AWS Doc")
        url = d.get("url", "")
        content = d.get("content", "")
        blocks.append(f"### {title}\nSource: {url}\n\n{content}")
        if url: 
            sources_with_titles.append({"title": title, "url": url})
        
    return "\n\n---\n\n".join(blocks), sources_with_titles

def summarize_question(question: str) -> str:
    summary_chain = summary_prompt | llm | StrOutputParser()
    return summary_chain.invoke({"question": question})

def prepare_inputs(question: str) -> dict:
    summarized_question = summarize_question(question)
    
    kb_docs = knowledge_base_fetch(summarized_question)
    kb_ctx, kb_sources = knowledge_base_format(kb_docs)
    
    mcp_docs = mcp_fetch_from_fargate(summarized_question)
    mcp_ctx, mcp_sources = mcp_format(mcp_docs)

    return {
        "kb_context": kb_ctx, "kb_sources": kb_sources,
        "mcp_context": mcp_ctx, "mcp_sources": mcp_sources,
        "question": question,
    }

prepare_runnable = RunnableLambda(prepare_inputs)

final_chain = prepare_runnable | RunnableParallel(
    answer=(prompt | llm | StrOutputParser()),
    kb_sources=lambda x: x.get("kb_sources", []),
    mcp_sources=lambda x: x.get("mcp_sources", [])
)



def main(event, context):
    logger.info(f"RAG Chain Lambda 시작: {event}")
    
    channel_id = event.get("channel_id")
    thread_ts = event.get("thread_ts")
    user_question = event.get("user_question")

    if not all([channel_id, thread_ts, user_question]):
        logger.error("channel_id, thread_ts, user_question 필드 X")
        return

    try:
        result = final_chain.invoke(user_question)
        answer = result.get("answer", "답변을 생성하지 못했습니다...")
        kb_sources = result.get("kb_sources", [])
        mcp_sources = result.get("mcp_sources", [])

        blocks = [
            {"type": "section", "text": {"type": "mrkdwn", "text": answer}}
        ]
        if kb_sources or mcp_sources:
            blocks.append({"type": "divider"})
            source_texts = []
            for i, src in enumerate(kb_sources, 1):
                source_texts.append(f"• <{src['slack']}|Slack 스레드 #{i}>")
            for src in mcp_sources:
                title = src.get('title', '공식 문서')
                url = src.get('url')
                if url:
                    source_texts.append(f"• <{url}|{title}>")
            
            if source_texts:
                blocks.append({
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "*아래 자료들도 확인해보세요!* :blob_smiley: \n" + "\n".join(source_texts)}
                })

        slack_client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=f"답변: {answer}",
            blocks=blocks
        )
        logger.info("Slack에 답변 전송 성공")

        try:
            slack_client.reactions_remove(
                channel=channel_id,
                name="bbengle",
                timestamp=thread_ts
            )
        except SlackApiError as e:
            logger.warning(f"bbengle 리액션 삭제 실패: {e}")

        # 완료 리액션(:bongo_blob:) 추가
        try:
            slack_client.reactions_add(
                channel=channel_id,
                name="bongo_blob",
                timestamp=thread_ts
            )
        except SlackApiError as e:
            logger.warning(f"bongo_blob 리액션 추가 실패: {e}")

    except Exception as e:
        logger.error(f"RAG 체인 실행중에 오류: {e}", exc_info=True)
        try:
            slack_client.chat_postMessage(
                channel=channel_id,
                thread_ts=thread_ts,
                text=f"오류가 발생하여 답변을 생성하지 못했습니다: {e}"
            )
        except SlackApiError as slack_e:
            logger.error(f"Slack 메시지 전송 실패: {slack_e}")
