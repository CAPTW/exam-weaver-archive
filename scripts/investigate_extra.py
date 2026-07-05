"""
Investigate the 4회 기관3 extra question issue
"""
import sys
import os
sys.path.insert(0, 'src')

import pypdf
import re

def investigate_extra():
    """Check for duplicate question"""
    print(f"\n{'='*50}")
    print("INVESTIGATING EXTRA QUESTION")
    print('='*50)
    
    q_path = "G:/내 드라이브/수업/시험자료 모음/2025/2025 3급 기관사.pdf"
    
    if not os.path.exists(q_path):
        print("File does not exist.")
        return

    try:
        from parser.question import QuestionParser
        from parser.extractor import PDFExtractor
        from parser.metadata import MetadataParser
        
        # Parse the 2025 PDF
        extractor = PDFExtractor(q_path)
        pages = extractor.extract_all()
        
        # Get metadata
        meta_parser = MetadataParser()
        metadata = meta_parser.parse_metadata(pages[0].text if pages else "")
        
        parser = QuestionParser(metadata.exam_type)
        questions = parser.parse_questions(pages)
        
        print(f"Total questions: {len(questions)}")
        
        # Group by subject
        by_subject = {}
        for q in questions:
            subj = q.subject_name or 'unknown'
            if subj not in by_subject:
                by_subject[subj] = []
            by_subject[subj].append(q)
        
        print(f"\nQuestions per subject:")
        for subj, qs in by_subject.items():
            count = len(qs)
            mark = "⚠️" if count != 25 else "✓"
            print(f"  {mark} {subj}: {count}")
            if count > 25:
                # Show which numbers appear
                nums = sorted([q.number for q in qs])
                print(f"      Numbers: {nums}")
                # Find duplicates
                from collections import Counter
                num_counts = Counter([q.number for q in qs])
                dups = [n for n, c in num_counts.items() if c > 1]
                if dups:
                    print(f"      Duplicate numbers: {dups}")
                extras = [n for n in nums if n > 25]
                if extras:
                    print(f"      Numbers > 25: {extras}")
                    
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    investigate_extra()
