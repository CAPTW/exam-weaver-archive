import sys
import os
import logging

# Add src to path
sys.path.append(os.path.abspath('src'))

from parser.main import ExamPDFParser

# Setup logging to see what's happening
logging.basicConfig(level=logging.INFO)

def test_parse():
    q_pdf = 'data/pdf/2022_202203.pdf'
    a_pdf = 'data/pdf/2022_2022_answer2.pdf'
    
    if not os.path.exists(q_pdf) or not os.path.exists(a_pdf):
        print("PDF files not found.")
        return

    parser = ExamPDFParser()
    try:
        result = parser.parse(q_pdf, a_pdf)
        print("\n" + "="*50)
        print("Parsing Successful!")
        print(f"Metadata: {result['metadata']}")
        print(f"Stats: {result['stats']}")
        print(f"Questions extracted: {len(result['questions'])}")
        print("="*50)
    except Exception as e:
        print(f"Parsing failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_parse()
