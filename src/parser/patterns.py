# src/parser/patterns.py
"""PDF 파싱을 위한 정규식 패턴 정의"""

import re

# ============ 문제 관련 패턴 ============

# 문제 시작 패턴: "1. ", "25.", "21.What" 등
# 2025 레이아웃 대응: 마침표, 괄호, 한글, 영문, 공백 뒤에 오는 문제 번호
# (?<![0-9])는 숫자 직후 (예: 22.5)를 방지
QUESTION_START = re.compile(r'(?<![0-9])([1-9]\d?)\.(?!\d)\s*')

# 선지 추출 패턴
CHOICE_PATTERN = re.compile(
    r'(㉮|㉯|㉴|㉵)\s*([^㉮㉯㉴㉵]+?)(?=\s*(?:㉮|㉯|㉴|㉵|\d+\.(?!\d)|$))',
    re.DOTALL
)

# 페이지 번호 패턴: "- 1 -", "- 25 -" 등
PAGE_NUMBER = re.compile(r'^-\s*(\d+)\s*-', re.MULTILINE)

# ============ 표지 관련 패턴 ============

# 표지 정보 추출: 연도, 회차
# 예: "2022년 제3회", "2022 1 자격시험"
COVER_INFO_LIST = [
    re.compile(r'(\d{4})\s*년\s*제?\s*(\d+)\s*회', re.DOTALL),
    re.compile(r'(\d{4})\s+([1-4])(?:\s+[가-힣A-Za-z]+)?(?:\s*시험)?', re.DOTALL),
    re.compile(r'(\d{4})\s*년.*?(\d+)\s*회', re.DOTALL)
]

# 시험 종류 추출
# 예: "3급 기관사", "3급항해사", "급기관사3"
EXAM_TYPE_LIST = [
    re.compile(r'(\d)급\s*(\w+사)'),
    re.compile(r'급\s*(\w+사)(\d)')
]

# 호환성을 위한 기본 패턴 (첫 번째 사용)
COVER_INFO = COVER_INFO_LIST[0]
EXAM_TYPE = EXAM_TYPE_LIST[0]

# 표지 식별 키워드 (너무 일반적인 단어는 제외)
COVER_INDICATORS = ['문 제 지', '문  제  지', '자격시험', '정기시험', '기출']

# ============ 정답지 관련 패턴 ============

# 정답지 헤더
# 예: "< 5급 기관사 > 답안", "급 기관사 답안 < 1 >"
ANSWER_HEADER_LIST = [
    re.compile(r'<\s*(\d)\s*급?\s*(\w+)\s*(?:\(([^)]+)\))?\s*>\s*답안'),
    re.compile(r'급\s*(\w+)\s*답안\s*<\s*(\d+)\s*.*?>(?:\s*\(([^)]+)\))?')
]

# 정답지 회차
# 예: "◎ 2022년 제 1회 정기시험", "년 제 회 정기시험2022 1◎"
ANSWER_SESSION_LIST = [
    re.compile(r'◎\s*(\d{4})\s*년?\s*제?\s*(\d)\s*회?(?:\s*정기시험)?'),
    re.compile(r'년\s*제\s*회\s*정기시험\s*(\d{4})\s*(\d)'),
    re.compile(r'(\d{4})\s*년?\s*제?\s*(\d)\s*회?(?:\s*정기시험)?'),
    re.compile(r'(?:\d{4}년\s*제\d회\s*)?정기시험\s*(\d{4})\s*제?\s*(\d)\s*회?')
]

# 호환성
ANSWER_HEADER = ANSWER_HEADER_LIST[0]
ANSWER_SESSION = ANSWER_SESSION_LIST[0]

# 과목별 정답 (일반 형식)
SUBJECT_ANSWER_COMPACT = re.compile(
    r'^(기관\d|직무일반|영어|항해|운용|법규|상선전문)\s*([가나사아])\s*[ \n]+([가나사아\s]+)',
    re.MULTILINE
)

# 과목별 정답 (국내한정 형식 - 공백 구분)
# 예: "기관1 사 사 나 ..." (한 줄에 있거나 줄바꿈 포함)
SUBJECT_ANSWER_SPACED = re.compile(
    r'^(기관\d|직무일반|영어|항해|항해사|운용|법규)\s+((?:[가나사아]\s*){25})',
    re.MULTILINE
)

# ============ 2025 Grid 형식 패턴 ============

# 2025 정답 그리드: 문제 번호 행 (1 2 3 4 ... 25)
ANSWER_GRID_NUMBERS = re.compile(r'(?:^|\s)(\d{1,2})\s+(?=\d{1,2}\s)', re.MULTILINE)

# 2025 정답 그리드: 정답 문자 연속 (가 나 사 아 ...)
ANSWER_GRID_CHARS = re.compile(r'([가나사아])\s*', re.MULTILINE)

# 2025 회차 구분: "제N회" 또는 "N회"
SESSION_MARKER_2025 = re.compile(r'제?\s*(\d)\s*회')

# ============ 매핑 테이블 ============

# 선지 기호 → 번호
CHOICE_SYMBOL_TO_NUMBER = {
    '㉮': 1,
    '㉯': 2,
    '㉴': 3,
    '㉵': 4,
    '⑤': 5
}

# 정답 문자 → 번호
ANSWER_CHAR_TO_NUMBER = {
    '가': 1,
    '나': 2,
    '사': 3,
    '아': 4
}

# 번호 → 선지 기호
NUMBER_TO_CHOICE_SYMBOL = {v: k for k, v in CHOICE_SYMBOL_TO_NUMBER.items()}

# 과목 이름 → 코드
SUBJECT_NAME_TO_CODE = {
    '기관1': 'engine1',
    '기관2': 'engine2',
    '기관3': 'engine3',
    '기관': 'engine',
    '직무일반': 'general',
    '영어': 'english',
    '항해': 'navigation',
    '운용': 'operation',
    '법규': 'regulation',
    '상선전문': 'merchant',
    '어선전문': 'fishing'
}

# 시험별 과목 순서
ENGINE_FULL_SUBJECTS = ['기관1', '기관2', '기관3', '직무일반', '영어']
ENGINE_LIMITED_SUBJECTS = ['기관1', '기관2', '기관3', '직무일반']
MERCHANT_NAVIGATION_FULL_SUBJECTS = ['항해', '운용', '법규', '영어', '상선전문']
MERCHANT_NAVIGATION_LIMITED_SUBJECTS = ['항해', '운용', '법규', '상선전문']
FISHING_NAVIGATION_FULL_SUBJECTS = ['항해', '운용', '법규', '영어', '어선전문']
FISHING_NAVIGATION_LIMITED_SUBJECTS = ['항해', '운용', '법규', '어선전문']
SMALL_VESSEL_SUBJECTS = ['항해', '운용', '법규', '기관']

EXAM_SUBJECT_ORDER = {
    '소형선박조종사': SMALL_VESSEL_SUBJECTS,
    '1급기관사': ENGINE_FULL_SUBJECTS,
    '2급기관사': ENGINE_FULL_SUBJECTS,
    '3급기관사': ENGINE_FULL_SUBJECTS,
    '4급기관사': ENGINE_FULL_SUBJECTS,
    '5급기관사': ENGINE_FULL_SUBJECTS,
    '6급기관사': ENGINE_LIMITED_SUBJECTS,
    '1급기관사(국내)': ENGINE_LIMITED_SUBJECTS,
    '2급기관사(국내)': ENGINE_LIMITED_SUBJECTS,
    '3급기관사(국내)': ENGINE_LIMITED_SUBJECTS,
    '4급기관사(국내)': ENGINE_LIMITED_SUBJECTS,
    '5급기관사(국내)': ENGINE_LIMITED_SUBJECTS,
    '6급기관사(국내)': ENGINE_LIMITED_SUBJECTS,
    '1급항해사(상선)': MERCHANT_NAVIGATION_FULL_SUBJECTS,
    '2급항해사(상선)': MERCHANT_NAVIGATION_FULL_SUBJECTS,
    '3급항해사(상선)': MERCHANT_NAVIGATION_FULL_SUBJECTS,
    '4급항해사(상선)': MERCHANT_NAVIGATION_FULL_SUBJECTS,
    '5급항해사(상선)': MERCHANT_NAVIGATION_FULL_SUBJECTS,
    '6급항해사(상선)': MERCHANT_NAVIGATION_LIMITED_SUBJECTS,
    '1급항해사(어선)': FISHING_NAVIGATION_FULL_SUBJECTS,
    '2급항해사(어선)': FISHING_NAVIGATION_FULL_SUBJECTS,
    '3급항해사(어선)': FISHING_NAVIGATION_FULL_SUBJECTS,
    '4급항해사(어선)': FISHING_NAVIGATION_FULL_SUBJECTS,
    '5급항해사(어선)': FISHING_NAVIGATION_FULL_SUBJECTS,
    '6급항해사(어선)': FISHING_NAVIGATION_LIMITED_SUBJECTS,
    '1급항해사(국내 상선)': MERCHANT_NAVIGATION_LIMITED_SUBJECTS,
    '2급항해사(국내 상선)': MERCHANT_NAVIGATION_LIMITED_SUBJECTS,
    '3급항해사(국내 상선)': MERCHANT_NAVIGATION_LIMITED_SUBJECTS,
    '4급항해사(국내 상선)': MERCHANT_NAVIGATION_LIMITED_SUBJECTS,
    '5급항해사(국내 상선)': MERCHANT_NAVIGATION_LIMITED_SUBJECTS,
    '6급항해사(국내 상선)': MERCHANT_NAVIGATION_LIMITED_SUBJECTS,
    '1급항해사(국내 어선)': FISHING_NAVIGATION_LIMITED_SUBJECTS,
    '2급항해사(국내 어선)': FISHING_NAVIGATION_LIMITED_SUBJECTS,
    '3급항해사(국내 어선)': FISHING_NAVIGATION_LIMITED_SUBJECTS,
    '4급항해사(국내 어선)': FISHING_NAVIGATION_LIMITED_SUBJECTS,
    '5급항해사(국내 어선)': FISHING_NAVIGATION_LIMITED_SUBJECTS,
    '6급항해사(국내 어선)': FISHING_NAVIGATION_LIMITED_SUBJECTS,
}
