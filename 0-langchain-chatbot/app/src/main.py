import os
import streamlit as st
from dotenv import load_dotenv

from chain import get_chain

load_dotenv()

chain = get_chain()

st.set_page_config(page_title="오지라퍼", layout="wide")
st.title("오지라퍼")

# 세션 상태 초기화
if "messages" not in st.session_state:
    st.session_state.messages = []

# 대화 히스토리 출력
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.write(message["content"])

# 메인
if prompt := st.chat_input("질문을 입력해주세요."):
    # 세션에 메시지 추가
    st.session_state.messages.append({"role": "user", "content": prompt})
    
    # 메시지 사용자 롤로 출력
    with st.chat_message("user"):
        st.write(prompt)
    
    # 답변 생성
    with st.chat_message("assistant"):
        with st.spinner("검색 및 답변 생성 중.."):
            # 대화 컨텍스트를 포함한 질문 생성
            context_prompt = prompt
            if len(st.session_state.messages) > 1:
                # 마지막 3턴의 대화(1턴 == 사용자 + 답변)만 컨텍스트로 사용
                recent_messages = st.session_state.messages[-6:]
                context_parts = []
                for msg in recent_messages[:-1]:  # 현재 메시지 제외
                    if msg["role"] == "user":
                        context_parts.append(f"사용자: {msg['content']}")
                    else:
                        context_parts.append(f"오지라퍼: {msg['content']}")
                
                if context_parts:
                    context_prompt = f"이전 대화:\n{'\n'.join(context_parts)}\n\n현재 질문: {prompt}"
            
            # 체인
            collected_sources = {}
            
            def generate_response():
                for chunk in chain.stream(context_prompt):
                    # 답변 스트리밍
                    if "answer" in chunk:
                        yield chunk["answer"]
                    # 출처 정보 수집 (스트리밍과 병렬로)
                    for key in ["kb_sources", "mcp_sources", "summarized_question"]:
                        if key in chunk:
                            collected_sources[key] = chunk[key]
            
            # 스트리밍 응답 표시
            full_answer = st.write_stream(generate_response())
            
            # 수집된 정보로 result 구성
            result = {
                "answer": full_answer,
                "kb_sources": collected_sources.get("kb_sources", []),
                "mcp_sources": collected_sources.get("mcp_sources", []),
                "summarized_question": collected_sources.get("summarized_question", "")
            }
            
            # 출처
            st.markdown("---")
            st.markdown("**출처**")
            
            # Slack KB
            kb_srcs = result.get("kb_sources", [])
            if kb_srcs:
                with st.expander("Slack에서 이런 스레드들을 참고했어요!"):
                    for i, s in enumerate(kb_srcs, 1):
                        st.markdown(f"**[{i}]** {s.get('s3','')}  |  [참고한 슬랙 스레드]({s['slack']})")
            
            # 공식문서
            mcp_srcs = result.get("mcp_sources", [])
            if mcp_srcs:
                with st.expander("관련된 공식 문서들을 참고했어요!"):
                    for url in mcp_srcs:
                        st.markdown(f"- [{url}]({url})") # 마크다운 방식
            
            # 요약된 질문 표시
            if "summarized_question" in result:
                st.caption(f"검색에 사용된 질문 요약 버전: {result['summarized_question']}")
            
            # 답변 데이터 세션에 저장
            assistant_message = {
                "role": "assistant", 
                "content": result["answer"],
                "sources": {
                    "kb_sources": result.get("kb_sources", []),
                    "mcp_sources": result.get("mcp_sources", [])
                }
            }
            
            # 요약된 질문 저장
            if "summarized_question" in result:
                assistant_message["summarized_question"] = result["summarized_question"]
            
            st.session_state.messages.append(assistant_message) # 세션에 추가