# ch01 Reference Mining Notes

대상 장: **규정·정의·용어를 읽는 해사영어 기초**  
기준 장 카드: `chapter_cards/ch01_rule_english_foundations.yml`  
산출 YAML: `source_notes/ch01_source_notes.yml`

## Scope Decisions

- Zotero MCP는 현재 세션에 노출되지 않아 사용하지 못했다. YAML의 `zotero_item_key`는 모두 `TODO_ZOTERO_UNAVAILABLE`로 남겼다.
- 요청문은 `chapter_cards/ch03.yml`를 언급했지만, 실제 ch03은 `ch03_colreg_lights_shapes_sounds.yml`이다. ch01의 정식 장 카드인 `ch01_rule_english_foundations.yml`를 기준으로 reference mining을 수행했다.
- `citation_policy.md`, `book_spec.yml`, `source_note_registry.yml`, `exam_frequency_map.yml`, `exam_concept_matrix.yml`, `question_pattern_registry.yml`는 현재 프로젝트 루트에 없다. 따라서 concept/pattern ID는 장 카드의 provisional ID를 그대로 유지했다.
- 이 문서는 장 본문 초안이 아니다. 직접 인용 후보, paraphrase 후보, 근거 gap을 정리한 reference layer다.

## Concept Coverage Table

| Concept | Sections | Covered By | Coverage | Use In Chapter |
|---|---:|---|---|---|
| C-CH01-001 규정상 의무 강도: shall, must, may, should, prohibited | ch01_s01, ch01_s02, ch01_s06 | ch01_src_001 IMO SMCP; ch01_src_003 Justice Canada Present Indicative; ch01_src_004 Justice Canada Obligations; ch01_src_008 USCG Nav Rules; ch01_src_015 ISPS Code overview | Strong for concept teaching, partial for exact convention wording | 의무 강도 ladder, shall을 단순 미래로 보는 오해 교정, mandatory/recommendatory 구분 |
| C-CH01-002 정의문 구조: means, refers to, is defined as | ch01_s03, ch01_s06 | ch01_src_005 Justice Canada Definitions; ch01_src_006 Vienna Convention; ch01_src_008 USCG Nav Rules; ch01_src_010 MSC.496 SOLAS Ch. IV terms; ch01_src_012 IAMSAR amendment | Strong for definition-reading method, partial for IAMSAR exact definitions | 정의문 해부도, head term/definition body/condition/exception 분해 |
| C-CH01-003 조건·예외·범위 신호: where, when, unless, except, not less than, within | ch01_s02, ch01_s03, ch01_s06 | ch01_src_006 Vienna Convention; ch01_src_007 UNCLOS; ch01_src_008 USCG Nav Rules; ch01_src_014 MARPOL overview | Moderate | 빈칸형·정오형에서 조건절이 답을 바꾸는 worked example 설계 |
| C-CH01-004 해사 맥락 어휘: passage, underway, make way, muster, drill, datum, traffic lane | ch01_s04, ch01_s06 | ch01_src_007 UNCLOS; ch01_src_008 USCG Nav Rules; ch01_src_009 Korean COLREG translation; ch01_src_012 IAMSAR amendment; ch01_src_017 SMCP semantic similarity paper; ch01_src_018 miscommunication report | Moderate to strong, but some terms need full manual/glossary | false friend map, 일반영어 의미와 해사 맥락 의미 비교 |
| C-CH01-005 약어와 코드: ETA, MMSI, AIS, EPIRB, SART, OSC | ch01_s05, ch01_s06 | ch01_src_001 IMO SMCP; ch01_src_010 MSC.496 SOLAS Ch. IV; ch01_src_011 ITU-R M.585-8; ch01_src_012 IAMSAR amendment; ch01_src_013 SOLAS overview; ch01_src_016 SAR maritime English PDF | Strong for AIS/MMSI/EPIRB/SART, partial for OSC exact wording | 약어 기능별 패널, full form + function + situation drill |

## Source Evidence Need Coverage

| Need ID | Need | Status | Notes |
|---|---|---|---|
| SRC-CH01-001 | IMO SMCP glossary and general principles | Covered | A.918(22) PDF and IMO public SMCP page support message markers, Part A/B structure, simplified maritime communication. |
| SRC-CH01-002 | UNCLOS, COLREG, SOLAS, MARPOL, STCW, ISPS texts/extracts | Partially covered | UNCLOS, COLREG/USCG, SOLAS/MARPOL/ISPS overview, SOLAS Ch. IV amendment are collected. Current consolidated texts and exact regulation locators remain TODO. |
| SRC-CH01-003 | IAMSAR terminology references | Partially covered | IMO IAMSAR amendment circular supports SAR term families, but the full current manual is still needed for final wording. |
| SRC-CH01-004 | Maritime English teaching references | Covered secondary | IMO SMCP education section, KCI SMCP semantic similarity paper, and maritime miscommunication report support teaching design. |
| SRC-CH01-005 | Bilingual maritime glossary | Partially covered | Korean COLREG treaty translation and SAR maritime English training PDF are usable. A formal maritime terminology dictionary or project `glossary.yml` remains needed. |

## Direct Quote Candidates

Use only when exact wording matters. Keep all quotes short.

| Source Note | Candidate | Use Case | Risk |
|---|---|---|---|
| ch01_src_001 | Message marker labels: Instruction, Advice, Warning, Information, Question, Answer, Request, Intention | SMCP message marker list | Medium: labels are fine; do not copy phrase tables. |
| ch01_src_003 | "shall and must to create obligations and may to confer powers" | obligation ladder | Low: official public legal drafting guidance. |
| ch01_src_006 | "ordinary meaning ... context ... object and purpose" | treaty-reading principle | Low: short Article 31 keyword quote. |
| ch01_src_008 | "not at anchor, or made fast to the shore, or aground" | underway misconception note | Low: official USCG rules page. |
| ch01_src_010 | "AIS-SART means an automatic identification system search and rescue transmitter" | definition syntax / abbreviation expansion | Medium: IMO standard; quote only this short definition fragment if needed. |

## Misconception Targets With Source Support

| Misconception | Supported By | Treatment |
|---|---|---|
| shall을 단순 미래시제로 해석 | ch01_src_003, ch01_src_004, ch01_src_008 | "규정문 shall = 의무/요건 신호"로 설명하되, 현대 drafting guidance와 조약 원문 관행을 구분한다. |
| may를 항상 허가로만 해석 | ch01_src_003, ch01_src_004 | power/discretion/permission을 문맥별로 나눈다. |
| means 뒤 첫 명사만 보고 답 선택 | ch01_src_005, ch01_src_010, ch01_src_012 | 정의부 전체와 조건·예외를 bracket annotation으로 표시한다. |
| underway를 "움직이는 중"으로만 해석 | ch01_src_008, ch01_src_009 | COLREG 정의에 근거해 anchor/shore/aground 여부 중심으로 교정한다. |
| 약어를 full form만 암기하고 기능을 모름 | ch01_src_010, ch01_src_011, ch01_src_013 | AIS/MMSI/EPIRB/SART를 통신·식별·조난·구조 기능으로 분류한다. |
| 한국어 번역어를 그대로 영어 문항에 대입 | ch01_src_009, ch01_src_016, ch01_src_017 | bilingual note에서 번역어는 보조이고, 영문 정의 구조가 우선임을 강조한다. |

## Unsupported Claims To Keep As TODO

| TODO ID | Claim | Why Unsupported | Needed Next |
|---|---|---|---|
| TODO-CH01-001 | shall/may/must 유형의 연도별 기출 횟수 | project-level frequency/pattern registry가 없음 | `exam_frequency_map.yml`, `question_pattern_registry.yml` 생성 |
| TODO-CH01-002 | SOLAS/MARPOL/STCW/ISPS의 최신 조문 wording | 공개 개요와 일부 결의문만 확보 | 최신 통합판 또는 authorized extracts 확보 |
| TODO-CH01-003 | IAMSAR phase/OSC/datum의 최종 exact definition | 개정 회람은 확보했지만 full current manual은 미확보 | IAMSAR Manual Vol. I/II/III 확인 |
| TODO-CH01-004 | 한국어 해사 용어 표준 번역의 최종 권장어 | 공식 용어사전 PDF fetch 실패, project glossary 부재 | IMO KOREA 용어집, 학교/기관 glossary 수집 |
| TODO-CH01-005 | 국내 해경 수험생 오답률 기반 난도 | 기출 빈도만 있고 실제 오답률 데이터 없음 | 모의고사/수업 진단 결과 item analysis |

## Citation And Copyright Risk Notes

- IMO SMCP, MSC resolutions, IAMSAR 자료는 표준·공식 문서이지만 phrase list, glossary, examples, figures, tables를 길게 복제하면 위험하다. 장 본문은 paraphrase와 author-created examples 중심으로 작성한다.
- UN/USCG/Justice Canada/법제처 자료는 인용 위험이 낮지만, 그래도 조문·정의문은 필요한 짧은 구절만 직접 인용한다.
- KCI 논문과 PWSRCAC 보고서는 secondary support다. 연구의 수치, 표, 예시, 사고 사례를 장 본문에 가져오기 전에 full-text와 라이선스를 확인한다.
- `ch01_src_016` 한국어 교육 PDF는 bilingual support로만 사용한다. 원문 예문이나 표를 복제하지 않는다.
- 모든 figure는 직접 제작한다. IMO/ITU/IAMSAR의 표, diagram, message-flow를 그대로 재현하지 않는다.
- 시험 기출 원문은 reference layer에서 사용하지 않았다. 연습문제는 기출 패턴을 추상화한 original item으로 설계해야 한다.

## Recommended Next Step

1. `source_notes/ch01_source_notes.yml`를 `source_note_registry.yml`에 병합하거나, 프로젝트 표준 registry 파일을 새로 만든다.
2. SOLAS/MARPOL/STCW/ISPS/IAMSAR의 최신 공식 판본 또는 authorized extracts를 확보해 exact locator를 채운다.
3. `glossary.yml`를 만들고 ch01 용어(`shall`, `may`, `underway`, `passage`, `datum`, `MMSI`, `AIS`, `EPIRB`, `SART`, `OSC`)를 한영 병기로 등록한다.
4. 그 다음에야 ch01 본문 drafting으로 넘어간다.
