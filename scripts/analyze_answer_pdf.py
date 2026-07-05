import sys
import os
import pypdf
import re

def analyze_answer_structure(pdf_path):
    """Analyze 2025 answer PDF structure"""
    print(f"\n{'='*20} ANSWER PDF ANALYSIS {'='*20}")
    
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        print(f"Total Pages: {len(reader.pages)}")
        
        for i, page in enumerate(reader.pages[:5]):
            text = page.extract_text()
            print(f"\n--- Page {i+1} ---")
            
            # Find subject markers
            subjects = re.findall(r'(기관[123]|직무일반|영어)', text)
            print(f"Subjects found: {subjects}")
            
            # Find session markers
            sessions = re.findall(r'(\d)회|제(\d)회', text)
            print(f"Sessions found: {sessions}")
            
            # Find number rows (1 2 3 4 ... 25)
            num_rows = re.findall(r'((?:\d{1,2}\s+){10,})', text)
            print(f"Number rows: {len(num_rows)}")
            
            # Find answer rows (가 나 사 아 ...)
            ans_rows = re.findall(r'((?:[가나사아]\s*){10,})', text)
            print(f"Answer rows: {len(ans_rows)}")
            
            # Show first 1000 chars
            print(f"\nText preview:\n{text[:1500]}")
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    a_path = "G:/내 드라이브/수업/시험자료 모음/2025/2025 정답 모음.pdf"
    analyze_answer_structure(a_path)
