from langchain_aws import AmazonKnowledgeBasesRetriever
from langchain_aws.chat_models import ChatBedrock
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.runnables import RunnableParallel, RunnableLambda
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


import os
import asyncio
import json
from dotenv import load_dotenv

load_dotenv()

BEDROCK_KB_ID = os.getenv("BEDROCK_KB_ID")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID")
AWS_REGION = os.getenv("AWS_REGION")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID")
SLACK_WORKSPACE = os.getenv("SLACK_WORKSPACE")

SLACK_RELEVANCE_THRESHOLD = 0.3

# 프롬프트
prompt = ChatPromptTemplate.from_messages([
    ("system",
    "너의 이름은 '오지라퍼'야."
    "너가 할 일은 사용자의 질문에 친절하게 근거와 함께 답변하는거야."
    "아래 두개의 컨텍스트(Slack Knowledge Base, AWS Docs)를 참고하여 한국어로 정확하고 간결하게 답변해줘."
    "본문에는 출처 표기하지 말아줘. 아래에 따로 첨부할거야."
    "근거 혹은 질문이 부정확하다면, 추가 정보가 필요하다고 말해줘"),
    ("human",
    "질문: {question}\n\n"
    "[슬랙 스레드 컨텍스트]\n{kb_context}\n\n"
    "[AWS 공식문서 컨텍스트]\n{mcp_context}\n\n"
    "응답:")
])

summary_prompt = ChatPromptTemplate.from_messages([
        ("system", 
         "사용자의 질문을 검색에 최적화된 형태로 요약해줘."
         "문장 형태가 아닌, 핵심 키워드와 개념만으로 요약해줘."
         "검색 엔진이 관련 문서를 잘 찾을 수 있도록 핵심 용어를 유지해줘"
         "쉼표를 넣지 말고 단어의 조합으로 요약해줘"
         ),
        ("human", "질문: {question}\n\n검색용 요약:")
    ])


retriever = AmazonKnowledgeBasesRetriever(
    knowledge_base_id=BEDROCK_KB_ID,
    region_name=AWS_REGION,
    retrieval_config={
        "vectorSearchConfiguration": {
            "numberOfResults": 3,
            "overrideSearchType": "HYBRID"
        }
    },
)

llm = ChatBedrock(model_id=BEDROCK_MODEL_ID, region_name=AWS_REGION, streaming=True)

async def _mcp_fetch(question: str):
    try:
        # AWS Documentation MCP 서버 (로컬 실행)
        client = MultiServerMCPClient({
            "aws-documentation-mcp-server": {
                "command": "uvx",
                "args": ["awslabs.aws-documentation-mcp-server@latest"],
                "transport": "stdio",
                "env": {
                    "FASTMCP_LOG_LEVEL": "ERROR",
                    "AWS_DOCUMENTATION_PARTITION": "aws"
                }
            }
        })

        async with client.session("aws-documentation-mcp-server") as session:
            tools = await load_mcp_tools(session)
            
            print(f"MCP tools: {[t.name for t in tools]}")
            
            # 사용할 수 있는 도구 찾기
            search_tool = next((t for t in tools if t.name == "search_documentation"), None)
            read_tool = next((t for t in tools if t.name == "read_documentation"), None)
            
            if not search_tool:
                print("search_documentation tools not found")
                return []
            
            # AWS 문서 검색 실행
            search_result = await search_tool.ainvoke({"search_phrase": question, "limit": 5})
            
            
            # 검색 결과에서 상위 몇 개 문서의 내용을 읽어오기
            out = []
            if isinstance(search_result, list):
                for i, result_str in enumerate(search_result[:3]):  # 상위 3개만 가져오기!
                    try:
                        # 각 결과의 형태가 json
                        result = json.loads(result_str)
                        
                        
                        url = result.get("url", "")
                        title = result.get("title", "")
                        context = result.get("context", "")
                        
                        if url and read_tool:
                            # 문서 내용 읽기 시도
                            try:
                                doc_content = await read_tool.ainvoke({"url": url})
                                out.append({
                                    "title": title,
                                    "url": url,
                                    "content": doc_content[:1500]  # 내용을 1500자로 제한
                                })
                            except Exception as read_error:
                                print(f"문서 읽기 실패 ({url}): {read_error}")
                                # 읽기 실패 시 검색 결과 컨텍스트 사용
                                out.append({
                                    "title": title,
                                    "url": url,
                                    "content": context
                                })
                        else:
                            # 읽기 도구가 없으면 검색 결과 컨텍스트만 사용
                            out.append({
                                "title": title,
                                "url": url,
                                "content": context
                            })
                            
                    except Exception as e:
                        print(f"검색 결과 파싱 오류: {e}")
                        continue
            
            print(f"최종 처리된 문서: {len(out)}개")
            return out
            
    except Exception as e:
        import traceback
        print(f"MCP fetch 에러: {e}")
        print(f"Full traceback: {traceback.format_exc()}") # 에러 추적
        return []
    
def mcp_fetch_sync(question: str):
    try:
        return asyncio.run(_mcp_fetch(question))
    except Exception as e:
        import traceback
        print(f"MCP sync fetch 에러: {e}")
        print(f"Full traceback: {traceback.format_exc()}")
        return []
    
def knowledge_base_fetch(q: str):
    return retriever.invoke(q)

def knowledge_base_format(threads):
    if not threads:
        return "KB 컨텍스트 없음", []
    
    blocks, sources = [], []
    filtered_count = 0
    
    for i, d in enumerate(threads, 1):
        score = d.metadata.get('score', 0.0) # score 가져오기
        print(f"KB 결과 {i}: score={score}")
        
        # 임계값 미달 시 제외
        if score < SLACK_RELEVANCE_THRESHOLD:
            print(f"KB 결과 {i} 제외됨 (점수: {score} < {SLACK_RELEVANCE_THRESHOLD})")
            filtered_count += 1
            continue
            
        meta = d.metadata or {}
        
        loc = meta.get("location", {})
        loc_s3 = loc.get("s3Location", {})
        s3u = loc_s3.get("uri", "")

        # 슬랙 스레드 링크
        link = slack_link_from_s3_uri(s3u, SLACK_CHANNEL_ID, SLACK_WORKSPACE)

        header = f"[KB {len(blocks)+1}] {s3u}" + (f"  |  Slack: {link}" if link else "")
        blocks.append(f"{header}\n{d.page_content}")

        sources.append({"s3": s3u, "slack": link})

    print(f"KB 필터링 결과: {len(sources)}개 유지, {filtered_count}개 제외")
    
    if not blocks:
        return "관련성이 높은 KB 결과가 없습니다", []
        
    return "\n\n---\n\n".join(blocks), sources

def mcp_format(docs: list[dict]) -> tuple[str, list[str]]:
    if not docs:
        return "MCP 컨텍스트 없음", []
    
    blocks, urls = [], []
    
    for i, d in enumerate(docs, 1):
        title = d.get("title", "AWS Doc")
        url   = d.get("url", "")
        md    = d.get("content", d.get("markdown", ""))
        
        blocks.append(f"### {title}\nSource: {url}\n\n{md}")
        if url: urls.append(url)
        
    return "\n\n---\n\n".join(blocks), urls


def summarize_question(question: str) -> str:
    summary_chain = summary_prompt | llm | StrOutputParser()
    return summary_chain.invoke({"question": question})

def prepare_inputs(question: str) -> dict:
    # 질문 요약
    summarized_question = summarize_question(question)
    
    # 요약ver 질문으로 검색
    kb_docs = knowledge_base_fetch(summarized_question)
    kb_ctx, kb_sources = knowledge_base_format(kb_docs)
    mcp_docs = mcp_fetch_sync(summarized_question)
    mcp_ctx, mcp_sources = mcp_format(mcp_docs)

    return {
        "kb_context": kb_ctx,
        "kb_sources": kb_sources,
        "mcp_context": mcp_ctx,
        "mcp_sources": mcp_sources,
        "question": question,
        "summarized_question": summarized_question
    }

def pick_slack(d): return d["kb_sources"]
def pick_docs(d): return d["mcp_sources"]
def pick_summarized_version(d): return d["summarized_question"]

prepare = RunnableLambda(prepare_inputs)

def get_chain():
    return (prepare | RunnableParallel(
        answer = (prompt | llm | StrOutputParser()),
        kb_sources = RunnableLambda(pick_slack),
        mcp_sources = RunnableLambda(pick_docs),
        summarized_question = RunnableLambda(pick_summarized_version),
    ))

def slack_link_from_s3_uri(
    s3_uri: str,
    channel_id: str,
    workspace_host: str,
) -> str:
    filename = os.path.basename(s3_uri.split("/", 3)[-1])
    ts = os.path.splitext(filename)[0].replace(".", "")

    return f"https://{workspace_host}/archives/{channel_id}/p{ts}"
