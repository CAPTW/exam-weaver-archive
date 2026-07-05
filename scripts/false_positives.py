"""
Check what false positives the current pattern is matching
"""
import sys
import os
sys.path.insert(0, 'src')

import pypdf
import re
from parser.patterns import QUESTION_START, PAGE_NUMBER

def find_false_positives(pdf_path):
    """Find false positive matches (non-question matches)"""
    print(f"\n{'='*20} FALSE POSITIVE ANALYSIS {'='*20}")

    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        
        # Analyze first 5 pages
        for page_idx in range(min(5, len(reader.pages))):
            text = reader.pages[page_idx].extract_text()
            text_clean = PAGE_NUMBER.sub('', text)
            
            print(f"\n=== Page {page_idx + 1} ===")
            
            # Find all matches
            for m in QUESTION_START.finditer(text_clean):
                num = int(m.group(1))
                start = max(0, m.start() - 20)
                end = min(len(text_clean), m.end() + 30)
                context = text_clean[start:end].replace('\n', ' ')
                
                # Check if this looks like a non-question context
                before = text_clean[max(0, m.start()-10):m.start()]
                
                # Likely false positive patterns
                is_date = '20' in before[-5:] or '년' in before or '월' in before
                is_time = ':' in before[-5:]
                is_header = '회' in before[-10:] and '제' in before[-10:]
                
                if is_date or is_time or is_header or num > 25:
                    print(f"  FALSE? [{num}] ...{context}...")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2025/2025 3급 기관사.pdf"
    find_false_positives(q_path)
