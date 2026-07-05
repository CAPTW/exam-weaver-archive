"""
Debug script to trace exactly what happens during question parsing
"""
import sys
import os
sys.path.insert(0, 'src')

import pypdf
import re
from parser.patterns import QUESTION_START, PAGE_NUMBER

def trace_parsing(pdf_path):
    """Trace how questions are parsed page by page"""
    print(f"\n{'='*20} PARSING TRACE {'='*20}")
    
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        
        all_parsed_nums = []
        
        for page_idx in range(min(20, len(reader.pages))):  # First 20 pages
            text = reader.pages[page_idx].extract_text()
            
            # Remove page numbers like we do in question.py
            text_clean = PAGE_NUMBER.sub('', text)
            
            # Split by QUESTION_START pattern
            parts = QUESTION_START.split(text_clean)
            
            parsed_nums = []
            i = 1
            while i < len(parts):
                try:
                    q_num = int(parts[i])
                    parsed_nums.append(q_num)
                    i += 2
                except (ValueError, IndexError):
                    i += 1
            
            all_parsed_nums.extend(parsed_nums)
            
            if parsed_nums:
                print(f"Page {page_idx + 1}: {parsed_nums}")
        
        # Count occurrences of each number
        from collections import Counter
        counts = Counter(all_parsed_nums)
        
        print(f"\n=== Summary (first 20 pages) ===")
        print(f"Total questions parsed: {len(all_parsed_nums)}")
        
        # Check for missing numbers 1-25 that should appear multiple times
        for num in range(1, 26):
            if counts[num] < 4:  # Should appear at least 4 times for 4 sessions
                print(f"  Number {num}: {counts[num]} occurrences (expected ~4)")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/시험자료 모음/2025/2025 3급 기관사.pdf"
    trace_parsing(q_path)
