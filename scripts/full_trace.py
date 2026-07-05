"""
Complete trace of 2020 answer parsing - Fixed
"""
import sys
import os
sys.path.insert(0, 'src')

import pypdf
import re

from parser.answer import AnswerParser, ANSWER_CHAR_TO_NUMBER
from parser.extractor import PDFExtractor

def full_trace():
    """Full trace of 2020 answer parsing"""
    print(f"\n{'='*50}")
    print("FULL TRACE OF 2020 ANSWER PARSING")
    print('='*50)
    
    answer_path = "G:/내 드라이브/수업/시험자료 모음/2020/2020 3급기관답안.pdf"
    
    if not os.path.exists(answer_path):
        print(f"File does not exist: {answer_path}")
        return

    try:
        # Step 1: Extract pages using PDFExtractor
        print("\n[Step 1] Extracting pages using PDFExtractor.extract()...")
        extractor = PDFExtractor()
        content = extractor.extract(answer_path)
        pages = content.pages
        print(f"Extracted {len(pages)} pages")
        for i, page in enumerate(pages):
            print(f"  Page {i+1}: {len(page.text)} chars")
            print(f"    First 200 chars: {page.text[:200]}...")
        
        # Step 2: Parse answers
        print("\n[Step 2] Parsing answers...")
        parser = AnswerParser()
        results = parser.parse_answers(pages, exam_type="3급기관사")
        print(f"Results: {len(results)} keys")
        for key, answers in results.items():
            print(f"  Key: {key}")
            print(f"  Answers: {len(answers)} - {answers[:5]}...")
        
        # Step 3: Show session detection
        print("\n[Step 3] Session detection from text...")
        full_text = pages[0].text if pages else ""
        
        # Try find_first_session
        year_only = re.search(r'(20\d{2})', full_text)
        session = re.search(r'제\s*(\d)\s*회', full_text)
        print(f"  Year pattern: {year_only.group(1) if year_only else 'NOT FOUND'}")
        print(f"  Session pattern: {session.group(1) if session else 'NOT FOUND'}")
        
        # Step 4: Expected key format
        print("\n[Step 4] Expected key format from question PDF...")
        print("  Expected: (2020, 2, '3급기관사', 'subject')")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    full_trace()
