import sys
import os
import pypdf

def dump_text(pdf_path, pages_to_read=3):
    print(f"\n--- Checking: {pdf_path} ---")
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        print(f"Total Pages: {len(reader.pages)}")
        for i in range(min(pages_to_read, len(reader.pages))):
            print(f"\n[Page {i+1}]")
            text = reader.pages[i].extract_text()
            # Print first 500 chars and some samples of question numbers if found
            print(text[:1000])
            print("\n" + "-"*30)
    except Exception as e:
        print(f"Error reading PDF: {e}")

if __name__ == "__main__":
    # Use the paths provided by the user
    q_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2020/해기사-2020-정기-2-3급기관사.pdf"
    a_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2020/2020 3급기관답안.pdf"
    
    dump_text(q_path)
    dump_text(a_path)
