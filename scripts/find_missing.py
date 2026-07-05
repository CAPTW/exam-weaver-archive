import sys
import os
import pypdf
import re

def find_missing_patterns(pdf_path):
    """Find why specific question numbers are missing"""
    print(f"\n{'='*20} MISSING QUESTION ANALYSIS {'='*20}")
    
    # Missing numbers from user report
    missing_numbers = {
        '1회': {'기관2': [7], '기관3': [2, 7], '영어': [4, 25]},
        '2회': {'기관1': [10], '기관3': [5, 8, 12, 18]},
        '3회': {'기관1': [8], '기관2': [9, 17], '기관3': [3, 6, 7], '영어': [6]},
        '4회': {'기관1': [3], '기관3': [6]}
    }
    
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
        
        # Search for each missing number pattern
        all_missing = [2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 17, 18, 25]
        
        print("\nSearching for missing numbers in text...")
        for num in sorted(set(all_missing)):
            # Find all occurrences of this number followed by a period
            pattern = re.compile(rf'(.{{0,20}})({num})\.(.*?)(?=\d{{1,2}}\.|$)', re.DOTALL)
            matches = list(pattern.finditer(full_text[:50000]))  # First 50k chars
            
            print(f"\n=== Number {num} ===")
            print(f"Found {len(matches)} occurrences")
            
            for i, m in enumerate(matches[:3]):  # Show first 3
                before = m.group(1)[-15:].replace('\n', '\\n')
                after = m.group(3)[:30].replace('\n', '\\n')
                print(f"  [{i+1}] ...{repr(before)} | {num}. | {repr(after)}...")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/시험자료 모음/2025/2025 3급 기관사.pdf"
    find_missing_patterns(q_path)
