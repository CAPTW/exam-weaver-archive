"""
Deep analysis: What exactly is happening with the missing questions?
"""
import sys
import os
sys.path.insert(0, 'src')

import pypdf
import re

def deep_analysis(pdf_path):
    """Analyze the exact text structure around missing question numbers"""
    print(f"\n{'='*50}")
    print("DEEP ANALYSIS OF MISSING QUESTIONS")
    print('='*50)

    # From user's error report, these are the missing numbers per subject/session
    missing_by_session = {
        '1회': {'기관2': [7], '기관3': [2, 7], '영어': [4, 25]},
        '2회': {'기관1': [10], '기관3': [5, 8, 12, 18]},
        '3회': {'기관1': [8], '기관2': [9, 17], '기관3': [3, 6, 7], '영어': [6]},
        '4회': {'기관1': [3], '기관3': [6]}
    }
    
    # All unique missing numbers
    all_missing = set()
    for session_data in missing_by_session.values():
        for nums in session_data.values():
            all_missing.update(nums)
    
    print(f"Unique missing numbers: {sorted(all_missing)}")
    
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text()
        
        print(f"\nTotal text length: {len(full_text)} characters")
        
        # For each missing number, find ALL occurrences and show context
        for num in sorted(all_missing):
            print(f"\n{'='*30}")
            print(f"SEARCHING FOR: {num}.")
            print('='*30)
            
            # Find all patterns that could be question number N
            # Use very loose pattern to catch everything
            pattern = re.compile(rf'(.{{0,30}}){num}\.(.{{0,50}})', re.DOTALL)
            matches = list(pattern.finditer(full_text))
            
            print(f"Total occurrences of '{num}.': {len(matches)}")
            
            # Show first 5 matches
            for i, m in enumerate(matches[:5]):
                before = m.group(1).replace('\n', '↵')[-20:]
                after = m.group(2).replace('\n', '↵')[:30]
                
                # Determine what character comes immediately before the number
                full_before = m.group(1)
                if full_before:
                    char_before = repr(full_before[-1])
                else:
                    char_before = "^START"
                
                print(f"  [{i+1}] char_before={char_before}")
                print(f"      ...{before} | {num}. | {after}...")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2025/2025 3급 기관사.pdf"
    deep_analysis(q_path)
