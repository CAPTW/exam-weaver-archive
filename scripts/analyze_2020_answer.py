"""
Analyze 2020 answer PDF structure
"""
import sys
import os
sys.path.insert(0, 'src')

import pypdf

def analyze_2020_answer_pdf():
    """Analyze the 2020 answer PDF structure"""
    print(f"\n{'='*50}")
    print("ANALYZING 2020 ANSWER PDF")
    print('='*50)
    
    if len(sys.argv) < 2:
        print("Usage: python scripts/analyze_2020_answer.py <answer_pdf_path>")
        return

    answer_path = sys.argv[1]
    
    if not os.path.exists(answer_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(answer_path)
        
        print(f"Total pages: {len(reader.pages)}")
        print()
        
        # Show content of each page
        for page_idx, page in enumerate(reader.pages):
            text = page.extract_text()
            print(f"\n{'='*30} Page {page_idx + 1} {'='*30}")
            print(text[:2000] if len(text) > 2000 else text)
            print()
            
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_2020_answer_pdf()
