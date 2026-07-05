"""
Debug 2020 answer parsing flow - Fixed version
"""
import sys
import os
sys.path.insert(0, 'src')

import pypdf
import re

# Import answer parser
from parser.answer import AnswerParser, ANSWER_CHAR_TO_NUMBER

def debug_2020_parsing():
    """Debug the 2020 answer parsing"""
    print(f"\n{'='*50}")
    print("DEBUGGING 2020 ANSWER PARSING")
    print('='*50)
    
    answer_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2020/2020 3급기관답안.pdf"
    
    if not os.path.exists(answer_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(answer_path)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        print(f"Total text length: {len(full_text)}")
        print(f"\nRaw text (first 500 chars):")
        print(full_text[:500])
        print("...")
        
        # Test each extraction mode manually
        parser = AnswerParser()
        
        # 1. Count answer characters
        all_answers = re.findall(r'[가나사아]', full_text)
        print(f"\n[Step 1] Total answer characters found: {len(all_answers)}")
        print(f"First 30 answers: {all_answers[:30]}")
        
        # 2. Test Grid mode (subject name based)
        print(f"\n[Step 2] Testing Grid mode...")
        grid_results = parser._extract_grid_answers(full_text)
        print(f"Grid mode results: {len(grid_results)} subjects")
        for subj, answers in grid_results.items():
            print(f"  - {subj}: {len(answers)} answers")
        
        # 3. Test Table mode (sequential splitting)
        print(f"\n[Step 3] Testing Table mode...")
        table_results = parser._extract_table_answers(full_text)
        print(f"Table mode results: {len(table_results)} subjects")
        for subj, answers in table_results.items():
            print(f"  - {subj}: {len(answers)} answers")
            print(f"    First 5: {answers[:5]}")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_2020_parsing()
