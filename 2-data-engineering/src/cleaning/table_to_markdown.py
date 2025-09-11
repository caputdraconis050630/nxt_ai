from bs4 import BeautifulSoup
from typing import List

def make_markdown_table(rows: List[List[str]]) -> str:
    if not rows:
        return ""

    header = rows[0]
    body = rows[1:]

    def escape(x: str) -> str:
        return x.replace("\n", " ").strip()
    
    output = []
    output.append("| " + " | ".join(escape(h) for h in header) + " |")
    output.append("| " + " | ".join("---" for _ in header) + " |") # 헤더 행
    for r in body:
        output.append("| " + " | ".join(escape(cell) for cell in r) + " |")

    return "\n".join(output)

def html_table_to_markdown(html: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    md_tables: List[str] = []

    for table in soup.find_all("table"):
        rows: List[List[str]] = []

        # thead 가 있는 경우
        if table.find("thead"):
            for tr in table.find_all("tr"):
                cells = []
                if cells:
                    rows.append(cells)

        
        bodies = table.find_all("tbody") or [table]
        for body in bodies:
            for tr in body.find_all("tr"):
                cells = [cell.get_text(" ", strip=True) for cell in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
        
        if rows:
            md_tables.append(make_markdown_table(rows))
    return md_tables
            

def pdf_text_to_markdown(text: str) -> List[str]:
    lines = [l.strip() for l in text.splitlines()]
    groups: List[List[List[str]]] = []
    current: List[List[str]] = []

    def flush():
        nonlocal current, groups # 상위 함수의 변수 쓰겠다는 표시
        if current: 
            groups.append(current)
            current = [] # 초기화

    for l in lines:
        if not l:
            flush()
            continue
        # |가 많거나, \t가 있거나, 컴마가 많다면,, table로 추정
        if l.count("|")>=2:
            cells = [c.strip() for c in l.split("|") if c]
            current.append(cells)
        elif l.count("\t") >= 1:
            cells = [c.strip() for c in l.split("\t") if c]
            current.append(cells)
        elif l.count(",") >= 2:
            cells = [c.strip() for c in l.split(",") if c]
            current.append(cells)
        else:
            flush()
    flush()

    markdown_tables = []
    for g in groups:
        if g:
            markdown_tables.append(make_markdown_table(g))
    return markdown_tables


    

    


            