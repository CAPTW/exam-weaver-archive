import sys
import os
sys.path.append(os.getcwd())
from src.database.repository import ExamRepository
from src.exporter.docx import DocxExporter
from pathlib import Path

def test_export():
    repo = ExamRepository('./data/exam_bank.db')
    exporter = DocxExporter()
    
    # Get some questions including choices
    questions = repo.get_questions_with_choices(limit=5)
    if not questions:
        print("No questions found to export.")
        return

    output_path = './data/test_export.docx'
    print(f"Exporting {len(questions)} questions to {output_path}...")
    
    try:
        exporter.export("테스트 시험지", questions, output_path)
        if Path(output_path).exists():
            print("SUCCESS: File created.")
        else:
            print("FAILURE: File not found.")
    except Exception as e:
        print(f"FAILURE: {e}")

if __name__ == "__main__":
    test_export()
