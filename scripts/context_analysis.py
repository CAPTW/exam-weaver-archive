import sys
import os
import pypdf
import re

def detailed_context_analysis(pdf_path):
    """Analyze context around question numbers more carefully"""
    print(f"\n{'='*20} DETAILED CONTEXT ANALYSIS {'='*20}")
    
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        
        # Pattern that should match questions
        question_pattern = re.compile(r'(?<![0-9])([1-9]\d?)\.(?!\d)\s*')
        
        # Analyze first few pages to understand context
        for page_idx in range(min(5, len(reader.pages))):
            text = reader.pages[page_idx].extract_text()
            print(f"\n=== Page {page_idx + 1} ===")
            
            matches = list(question_pattern.finditer(text))
            print(f"Total matches: {len(matches)}")
            
            # Show surrounding context for numbers that are missing
            target_nums = [2, 3, 4, 5, 6, 7, 8, 9, 10]
            for m in matches:
                num = int(m.group(1))
                if num in target_nums:
                    start = max(0, m.start() - 30)
                    end = min(len(text), m.end() + 50)
                    context = text[start:end].replace('\n', '\\n')
                    print(f"  [{num}] ...{context}...")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2025/2025 3급 기관사.pdf"
    detailed_context_analysis(q_path)
