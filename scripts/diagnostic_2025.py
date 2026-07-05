import sys
import os
import pypdf

def dump_text(pdf_path, label, max_pages=3):
    print(f"\n{'='*20} {label} {'='*20}")
    print(f"Path: {pdf_path}")
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        print(f"Total Pages: {len(reader.pages)}")
        
        for i, page in enumerate(reader.pages[:max_pages]):
            text = page.extract_text()
            print(f"\n--- Page {i+1} START ---")
            print(text[:2000] if len(text) > 2000 else text)
            print(f"--- Page {i+1} END ---")
    except Exception as e:
        print(f"Error reading PDF: {e}")

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/시험자료 모음/2025/2025 3급 기관사.pdf"
    a_path = "G:/내 드라이브/수업/시험자료 모음/2025/2025 정답 모음.pdf"
    
    dump_text(q_path, "2025 QUESTION PDF", max_pages=5)
    dump_text(a_path, "2025 ANSWER PDF", max_pages=3)
