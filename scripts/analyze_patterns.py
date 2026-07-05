import sys
import os
import pypdf
import re

def analyze_missing_patterns(pdf_path):
    """Analyze what characters appear before question numbers"""
    print(f"\n{'='*20} PATTERN ANALYSIS {'='*20}")
    
    if not os.path.exists(pdf_path):
        print("File does not exist.")
        return

    try:
        reader = pypdf.PdfReader(pdf_path)
        full_text = ""
        for page in reader.pages:
            full_text += page.extract_text() + "\n"
        
        # Find ALL occurrences of "N." where N is 1-25
        all_numbers = re.compile(r'(.{0,10})(\d{1,2})\.(?!\d)')
        
        # Track what precedes each question number
        preceding_chars = {}
        for match in all_numbers.finditer(full_text):
            context = match.group(1)
            num = match.group(2)
            
            if int(num) <= 25:
                # Get the character immediately before the number
                if context:
                    last_char = context[-1] if context else '^'
                    char_type = 'hangul' if '\uac00' <= last_char <= '\ud7a3' else \
                               'space' if last_char.isspace() else \
                               'digit' if last_char.isdigit() else \
                               'alpha' if last_char.isalpha() else \
                               repr(last_char)
                    
                    key = (num, char_type)
                    if key not in preceding_chars:
                        preceding_chars[key] = []
                    preceding_chars[key].append(context)
        
        print(f"Total patterns found: {len(preceding_chars)}")
        print("\nPatterns by preceding character type:")
        
        # Group by char type
        by_type = {}
        for (num, char_type), contexts in preceding_chars.items():
            if char_type not in by_type:
                by_type[char_type] = 0
            by_type[char_type] += len(contexts)
        
        for char_type, count in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"  {char_type}: {count} occurrences")
        
        # Show examples of non-hangul, non-space patterns
        print("\nExamples of tricky patterns:")
        for (num, char_type), contexts in list(preceding_chars.items())[:20]:
            if char_type not in ['hangul', 'space']:
                print(f"  {num}. preceded by {char_type}: {repr(contexts[0][-5:] if contexts else '')}")
                
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    q_path = "G:/내 드라이브/수업/해기사 기출문제 모음/2025/2025 3급 기관사.pdf"
    analyze_missing_patterns(q_path)
