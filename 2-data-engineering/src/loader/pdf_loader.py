from dataclasses import dataclass
from typing import List, Dict, Any, Optional
import os
from pypdf import PdfReader

@dataclass
class Page:
    page: int
    content: str
    meta: Dict[str, Any]

@dataclass
class PDFLoadResult:
    source: str
    total_pages: int
    pages: List[Page]

def load_pdf(path: str, max_pages: Optional[int] = None) -> PDFLoadResult:
    if not os.path.exists(path):
        raise FileNotFoundError(f"File not found: {path}")
    
    abs_path = os.path.abspath(path)
    pages: List[Page] = []

    with open(abs_path, "rb") as f:
        reader = PdfReader(f)

        total = len(reader.pages)
        lim = total
        if max_pages:
            lim = min(total, max_pages)

        for i in range(lim):
            pages.append(Page(
                page = i+1,
                content = reader.pages[i].extract_text() or "",
                meta = {
                    "source": abs_path,
                    "page": i+1,
                    "total_pages": total
                }
            ))

    return PDFLoadResult(
        source = abs_path,
        total_pages = total,
        pages = pages
    )
        
            
