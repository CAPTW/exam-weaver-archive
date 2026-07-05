import sys
import os

# Add src to path
sys.path.append(os.path.abspath('src'))

# Fix missing package issues with relative imports by adding 'src' to path
# and making sure we can import as src.database.repository for example
# or just making src the root if the code expects that.

from database.repository import ExamRepository

def check_stats():
    db_path = 'data/exam_bank.db'
    if not os.path.exists(db_path):
        print("Database not found.")
        return

    repo = ExamRepository(db_path)
    try:
        stats = repo.get_statistics()
        print("\n" + "="*50)
        print("Database Statistics")
        print(f"Total Questions: {stats.get('total_questions', 0)}")
        print(f"Questions by year: {stats.get('by_year', {})}")
        print(f"Exams count: {stats.get('exam_count', 0)}")
        print(f"Subjects count: {stats.get('subject_count', 0)}")
        print("="*50)
    except Exception as e:
        print(f"Failed to get statistics: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_stats()
