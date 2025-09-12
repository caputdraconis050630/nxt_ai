import streamlit as st
import tempfile
import os
from dotenv import load_dotenv
from src.pipeline.pipeline import get_pipeline

load_dotenv()

pipeline = get_pipeline()

st.set_page_config(layout="wide")
st.title("Data Engineering Demo")

with st.sidebar:
    if pipeline:
        if st.button("인덱스 초기화", type="primary"):
            if pipeline.reset_index():
                st.success("인덱스 초기화 성공\n비동기로 처리되므로, 실제 반영에는 살짝 시간이 걸릴 수 있숩니다.")
            else:
                st.error("인덱스 초기화 실패")

# 메인 쪽
tab1, tab2 = st.tabs(["파이프라인", "결과 확인(검색))"])

# 파이프라인 쪽
with tab1:
    st.header("파이프라인")
    st.info("데이터 소스 선택 -> 정제 -> 청크 -> 인덱싱")
    
    col1, col2 = st.columns(2)
    with col1:
        source_type = st.radio("데이터 소스 선택:", ('PDF', 'Web URL'), horizontal=True, key="source_type")
        if source_type == 'PDF':
            uploaded_file = st.file_uploader("pdf 파일 업로드", type="pdf")
            source_input = uploaded_file
        else: # WebURL
            source_input = st.text_input("web url 입력", "https://python.org/") # 이게 그나마 가져오는 데이터가 안정적
    
    with col2:
        chunker_type = st.selectbox(
            "chunk 방법 선택:",
            ("recursive", "semantic", "fixed")
        )
        chunk_size = st.number_input("chunk size", min_value=100, max_value=8000, value=1000, step=100)
        
        # overlap은 fixed에만 노출
        chunk_overlap = 0
        if chunker_type == "fixed":
            chunk_overlap = st.number_input("chunk overlap", min_value=0, max_value=4000, value=100, step=50)

    if st.button("ingest 시작", disabled=(source_input is None)):
        source_path_or_url = ""
        if isinstance(source_input, str):
            source_path_or_url = source_input
        else:
            # PDF 파일 임시 저장
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(source_input.getvalue())
                source_path_or_url = tmp_file.name

        with st.status(f"ingest 중 '{source_path_or_url}'...", expanded=True) as status:
            try:
                # 파이프라인 실행
                docs = pipeline.run(
                    source=source_path_or_url,
                    chunker=chunker_type,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap
                )
                status.update(label=f"ingest 완료. {len(docs)} chunks", state="complete")
                st.subheader("청크 결과")
                st.json(docs, expanded=False)
            except Exception as e:
                status.update(label="ingest 실패", state="error")
                st.error(f"에러: {e}")
            finally:
                # PDF 파일 삭제
                if 'tmp_file' in locals() and os.path.exists(source_path_or_url):
                    os.remove(source_path_or_url)

# 결과 확인 쪽
with tab2:
    st.header("결과 확인(검색)")
    st.info("ingested한 데이터에 대해 검색.")

    query = st.text_input("입력:", key="query")
    
    if st.button("검색"):
        if not query:
            st.warning("검색어 엠티")
        else:
            with st.spinner("검색중"):
                try:
                    search_results = pipeline.search(query=query, k=10)
                    st.success(f"{len(search_results)}개의 검색결과")
                    
                    for result in search_results:
                        with st.expander(f"**점수: {result['score']:.4f}** - Source: {result['metadata'].get('source', 'N/A')}"):
                            st.markdown(result['page_content'])
                            st.json({"metadata": result['metadata']}, expanded=False)
                except Exception as e:
                    st.error(f"검색 중 에러: {e}")
