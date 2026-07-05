import sys
import os
sys.path.append(os.getcwd())
from src.parser.extractor import PDFExtractor

def debug_text(pdf_path):
    extractor = PDFExtractor()
    content = extractor.extract(pdf_path)
    
    print(f"Total Pages: {len(content.pages)}")
    
    for page in content.pages:
        if '기관' in page.text:
            print(f"\n{'='*40}")
            print(f"Page {page.number} (Found '기관')")
            print(f"{'='*40}")
            print(page.text)
            print(f"{'='*40}\n")
            break # Print first match only to avoid spam

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/debug_pdf_text.py <pdf_path>")
    else:
        debug_text(sys.argv[1])
