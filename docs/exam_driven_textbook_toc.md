# 해사영어 기출 기반 교재 목차 설계

## 설계 원칙

이 목차는 단기 암기용 요약서가 아니라, 반복 출제되는 문항 패턴 뒤의 개념 구조를 설명하는 교재를 목표로 한다. 원문 조항, 표준 통신 표현, 선박 운용 용어, 상황 판단 문제를 각각 분리하지 않고, 실제 시험에서 함께 작동하는 개념 흐름에 따라 배열했다.

분석 근거:
- `outputs/02_questions_master.csv`: 600문항 question-level master
- `outputs/03_topic_distribution.csv`: 주제별 출제 분포
- `outputs/04_year_subject_topic_matrix.csv`: 연도-과목-주제 매트릭스
- `outputs/05_recent_weighted_priority.csv`: 빈도 50%, 최근 3개년 30%, 난도/오답위험 20% 우선순위
- `outputs/06_methodology.md`: OCR 및 분류 한계
- `outputs/07_exam_strategy.md`: 학습 전략 요약

## 개정 목차

### Part I. 규정 영어와 해사 용어의 기초

1. **규정·정의·용어를 읽는 해사영어 기초**  
   해사영어 문항의 공통 언어 구조를 먼저 다룬다. `shall/may/must`, 조약식 정의문, 약어, 빈칸형 문장 구조를 익혀 뒤 장의 협약 원문 학습을 받쳐 준다.

### Part II. COLREG 항법 규칙과 시각·음향 신호

2. **COLREG 조우 상황과 피항 판단**  
   충돌위험 판단, safe speed, lookout, stand-on/give-way 관계, 추월·마주침·횡단 상황을 개념적으로 설명한다.

3. **COLREG 등화·형상물·음향신호**  
   선박 상태를 등화·형상물·음향신호로 읽는 법을 도표와 상황 그림 중심으로 학습한다.

### Part III. SMCP/VHF 통신과 선박 운용 언어

4. **SMCP 표준 표현과 Message Marker**  
   애매한 일반영어를 표준해사통신영어로 바꾸는 원리, message marker, 폐쇄형 확인 절차를 설명한다.

5. **VHF·VTS·조타명령·항로지정 통신**  
   VHF 교신 구조, VTS 보고, 표준조타명령, 항로지정 용어를 통합한다.

6. **선박 운용 상황 속 용어: 투묘·접안·선체·기관**  
   선박 운용 vocabulary를 단어 암기가 아니라 장면·절차·장비와 연결한다.

### Part IV. 선박 안전과 수색구조

7. **SOLAS 안전 의무와 비상대응 준비**  
   muster, drill, bridge visibility, safety organization 등 안전 규정을 의무 구조로 이해한다.

8. **IAMSAR 비상 단계·현장조정·수색 패턴**  
   uncertainty/alert/distress phase, OSC, search pattern을 상황 판단형 문제로 연결한다.

### Part V. 해양법과 컴플라이언스

9. **UNCLOS 해역·영해·무해통항**  
   해역 구조, 연안국 권한, 무해통항 판단 기준을 지도와 결정 트리로 학습한다.

10. **ISPS·STCW·MARPOL 컴플라이언스**  
    보안등급, 선원 훈련·자격·당직, 오염방지 의무를 cross-code 관점으로 비교한다.

### Appendix. 저빈도·지원 자료

A. 국제신호서와 통신 철자 코드  
B. 법규·협약 숫자 quick index  
C. bilingual glossary와 약어 master list  
D. 최근성은 낮지만 검토 가치가 있는 세부 규정: UNCLOS 추적권, SOLAS 구명설비·항해선교 시야, MARPOL 폐기물 배출, COLREG 제한시계·통항분리

## 장 순서 근거

1. **언어 기초를 맨 앞에 배치**  
   빈칸형 조문, 정의 비교, 약어, 번역 오류 문항이 전 범위에 걸쳐 반복되므로 첫 장에서 규정 영어 독해 도구를 제공한다. 다만 일반영어·독해는 최근 3개년 비중이 낮고 검토 필요 row가 많아 큰 독립 part로 확대하지 않는다.

2. **COLREG를 핵심 개념 첫 묶음으로 배치**  
   `COLREG 일반 항법규정`, `등화·형상물`, `항법·피항동작`은 빈도와 최근성이 모두 높고, 이후 VHF·VTS·조타명령·SAR 상황 판단의 선수 개념이다.

3. **SMCP/VHF와 운용 용어를 중반부에 배치**  
   `SMCP/VHF 표준해사통신`, `VHF·VTS·무선통신`, `Message Marker`, `표준조타명령`은 최근 3개년에서도 강하게 반복된다. COLREG 뒤에 배치해야 통신 표현이 실제 조선·항법 상황과 연결된다.

4. **SOLAS 후 IAMSAR 배치**  
   선박 내 비상조직과 훈련 개념을 먼저 세운 뒤, 조난·수색·현장조정으로 확장한다.

5. **UNCLOS와 컴플라이언스는 후반부 배치**  
   중요도는 높지만 조선·통신보다 선수 개념 의존성이 낮다. 개념 설명과 표·지도 중심으로 후반부에서 정리한다.

## Page Weight Blueprint

| Part | Chapter | Core page weight | Rationale |
|---|---:|---:|---|
| I | 1 | 7% | 전 범위 조문·정의 독해의 기반 |
| II | 2 | 12% | COLREG 일반 규정과 상황 판단 고빈도 |
| II | 3 | 10% | 등화·형상물·음향신호 최근성 높음 |
| III | 4 | 12% | SMCP 표준표현 최상위 우선순위 |
| III | 5 | 10% | VHF/VTS/조타명령 최근 출제 강함 |
| III | 6 | 8% | 선박운용 용어는 빈도 높으나 범위 분산 |
| IV | 7 | 9% | SOLAS 일반 안전규정 반복 |
| IV | 8 | 9% | IAMSAR 수색구조 일반 최상위 우선순위 |
| V | 9 | 9% | UNCLOS 영해·무해통항 최근성 높음 |
| V | 10 | 8% | ISPS 최근성 보강, STCW/MARPOL 비교 처리 |
| Appendix | A-D | 6% | 저빈도·색인·지원 자료 |

## 보존, 이동, 축소 판단

- 기존 `chapter_cards` 디렉터리가 없어 보존할 기존 chapter file은 없었다.
- 다만 blueprint상 계속 정당화되는 주제는 모두 본문 또는 부록에 명시했다.
- `International Code of Signals`, `SMCP 통신 철자·코드`, `UNCLOS 추적권`, `SOLAS 구명설비`, `MARPOL 폐기물 배출`, `COLREG 제한시계·통항분리`는 삭제하지 않고 부록 또는 본문 box로 이동한다.
- `일반영어·독해`는 원자료상 raw count가 크지만 최근성이 낮고 검토 필요 row가 많아 Part I의 기반 장 및 장내 vocabulary box로 축소한다.

