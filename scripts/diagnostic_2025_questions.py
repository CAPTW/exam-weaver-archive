import sys
import os
import pypdf
import re

def dump_full_text(pdf_path, max_pages=10):
    print(f"\n{'='*20} FULL TEXT DUMP {'='*20}")
    print(f"Path: {pdf_path}")
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        print(f"Total Pages: {len(reader.pages)}")
        
        # Dump full text to see structure
        for i, page in enumerate(reader.pages[:max_pages]):
            text = page.extract_text()
            print(f"\n--- Page {i+1} (len={len(text)}) ---")
            
            # Show question number patterns found
            q_pattern = re.compile(r'(?:^|\s)(\d{1,2})\.(?!\d)', re.MULTILINE)
            matches = q_pattern.findall(text)
            print(f"Question numbers found: {matches}")
            
            # Show first 1500 chars
            print(text[:1500])
            print("..." if len(text) > 1500 else "")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/시험자료 모음/2025/2025 3급 기관사.pdf"
    dump_full_text(q_path)
