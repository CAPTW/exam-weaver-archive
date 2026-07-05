import sys
import os
import pypdf
import re

def dump_text(pdf_path, label):
    print(f"\n{'='*20} {label} {'='*20}")
    print(f"Path: {pdf_path}")
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        print(f"Total Pages: {len(reader.pages)}")
        
        # Start of each page indicator
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            print(f"\n--- Page {i+1} START ---")
            print(text)
            print(f"--- Page {i+1} END ---")
    except Exception as e:
        print(f"Error reading PDF: {e}")

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2020/해기사-2020-정기-2-3급기관사.pdf"
    a_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2020/2020 3급기관답안.pdf"
    
    # Dump enough to see the structure
    dump_text(q_path, "QUESTION PDF")
    dump_text(a_path, "ANSWER PDF")
