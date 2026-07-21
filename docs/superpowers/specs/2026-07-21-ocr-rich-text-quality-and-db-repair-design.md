# OCR Rich Text 품질 게이트 및 활성 DB 전수 교정 설계

## 목표

OCR 결과의 오타·오기와 손상된 선택 기호가 일반 발문과 선지뿐 아니라 `question_format_json`, `choice_format_json`, 공통 지문에 남은 채 DB에 저장되는 문제를 막는다. 현재 앱이 사용하는 활성 DB를 동일한 규칙으로 전수 검사하고, 원문 PDF로 확정한 변경만 안전하게 적용한다.

이 설계의 기본 원칙은 fail-closed이다. 문맥상 답이 하나뿐인 보수적 교정은 자동화하되, 원문 확인 없이 여러 해석이 가능한 텍스트는 추정 수정하지 않는다. 미확정 항목은 신규 임포트를 차단하거나 기존 DB 검토 보고서에 남긴다.

## 확인된 결함

- `validate_offline_question()`은 일반 stem과 choices만 검사하며 rich-text JSON의 표 셀을 검사하지 않는다.
- 기존 DB 감사는 `question_format_json`의 일부 표 텍스트를 검사하지만 `choice_format_json` 표 셀을 검사하지 않는다.
- 표의 중복 표현인 `rows`와 `cells[].text`가 일치하는지 검증하지 않는다.
- 현재 탐지 규칙은 `HaIf`, `f01그r`, `Da•elict`, `을지 않은`, `모두 개인가`와 같은 혼합 문자 및 문구 손상을 탐지하지 못한다.
- 2022년 3회 해사영어 3번은 실제 원본 PDF와 다르게 발문 및 `<보기>` 표가 저장되어 있지만 기존 dry-run 감사 결과에는 후보로 나타나지 않는다.

현재 감사기의 기준선 결과는 다음과 같다. 이 숫자는 정확한 오류 수가 아니라 기존 규칙이 찾은 후보 수이며, 누락이 존재함을 전제로 한다.

- `exam_bank.maritime_all.db`: 자동교정 후보 617건, 교정 후 잔여 의심 442건
- `exam_bank.user_workspace.db`: 자동교정 후보 0건, 잔여 의심 0건
- `exam_bank.Maritime.db`: 자동교정 후보 0건, 잔여 의심 0건. 알려진 오류를 놓치므로 탐지 공백의 증거이다.
- `data/exam_bank.db`: 자동교정 후보 591건, 교정 후 잔여 의심 443건

## 범위

교정 대상은 현재 앱이 사용하는 다음 네 DB로 한정한다.

- `data/domain_dbs/exam_bank.maritime_all.db`
- `data/domain_dbs/exam_bank.user_workspace.db`
- `data/domain_dbs/exam_bank.Maritime.db`
- `data/exam_bank.db`

`data/backups/`, `outputs/`, 임시 staging DB와 과거 빌드 산출물은 역사적 근거로 보존하고 수정하지 않는다.

검사할 저장 표면은 다음과 같다.

- `questions.question_text`
- `questions.question_format_json`의 모든 `tables[].rows[][]`와 `tables[].cells[].text`
- `question_choices.choice_text`
- `question_choices.choice_format_json`의 모든 `tables[].rows[][]`와 `tables[].cells[].text`
- `question_groups.shared_text`

사용자가 작성한 해설, 모범답안, 태그는 이번 OCR 교정 범위에 포함하지 않는다.

## 접근 방식

단순 치환 목록만 확대하는 방식은 새로운 OCR 변형이 생길 때마다 누락되므로 채택하지 않는다. 전체 PDF를 무조건 재OCR하여 DB를 새로 만드는 방식도 정상 데이터 회귀 위험이 크므로 기본 경로로 사용하지 않는다.

모든 표시 텍스트를 공통 계층으로 열거하고 동일한 교정·검사 규칙을 적용하는 계층형 방식을 사용한다.

1. `RichTextSurface`가 일반 텍스트, 표의 rows/cells, 공통 지문을 위치 정보와 함께 열거한다.
2. `ConservativeRepair`가 단일 해석만 가능한 고신뢰 규칙을 적용하고 변경 원장을 만든다.
3. `QualityGate`가 교정 후 모든 표면을 검사하고 구조 손상 및 모호한 OCR을 차단한다.
4. `SourceAudit`가 미확정 항목을 등록된 원본 PDF의 페이지와 대조한다.
5. `TransactionalDbRepair`가 원문으로 확정된 변경을 DB 복사본에 적용하고 검증 후 원자적으로 교체한다.

## RichTextSurface

공통 열거기는 각 텍스트에 다음 정보를 붙인다.

- 소유자 종류: question, choice, group
- DB row ID와 question ID
- 필드 경로
- 일반 텍스트 또는 JSON 표 좌표
- exam, subject, year, session, question number
- source URL과 source page
- 현재 텍스트

표의 `rows`와 `cells`는 둘 다 검사한다. 동일 좌표가 두 표현에 존재하면 텍스트가 정확히 일치해야 한다. 불일치는 자동으로 어느 쪽을 선택하지 않고 구조 오류로 분류한다. 확정 교정 시에는 두 표현을 함께 수정한다.

손상되거나 비객체인 format JSON도 조용히 무시하지 않고 구조 오류로 보고한다.

## 보수적 자동교정

자동교정은 다음 조건을 모두 만족해야 한다.

- 입력 패턴과 문맥이 명확하고 결과 후보가 하나이다.
- 숫자, 법령 번호, 수식, 고유명사 의미를 바꾸지 않는다.
- 교정 전후 값과 적용 규칙이 변경 원장에 기록된다.
- 교정 후에도 품질 게이트를 다시 통과한다.

교정 규칙은 일반 텍스트와 표 셀에 동일하게 적용한다. 이번 원본 사례처럼 특정 문항 전체의 정확한 전사가 필요한 경우에는 광범위한 전역 치환보다 source-confirmed repair registry를 사용한다.

## 품질 게이트

신규 파싱과 staging 저장 전 다음 순서를 강제한다.

1. OCR 및 구조 파싱
2. 모든 rich-text 표면 정규화
3. 보수적 자동교정
4. rows/cells 일치 검사
5. 모든 표면에 대한 텍스트 품질 검사
6. 통과 문항만 DB 저장

차단 사유에는 최소한 다음을 포함한다.

- 혼합 문자 OCR 토큰
- 영문 단어 안의 숫자·한글·특수문자 침입
- 손상된 원형 선택 기호 또는 연속 기호 누락
- 고신뢰 한국어 문구 손상
- 구분자 불균형
- invalid format JSON
- table rows/cells divergence
- 빈 표 셀 또는 비정상적인 문항/선지 혼입

차단 결과는 `blocked_quality` 상태와 함께 source URL, PDF page, 문항번호, 필드 경로, 문제 텍스트, 사유 코드를 보고서에 기록한다.

## 원문 대조 및 확정 교정

미확정 후보는 `source_url + source_page + question_number`로 원본 PDF를 연다. 소스가 이미지 PDF이면 등록된 페이지를 고해상도로 렌더링하여 대조한다.

source-confirmed repair에는 다음을 기록한다.

- DB 및 문항 식별자
- 원본 PDF 상대 또는 정규화 경로
- source page
- 필드 경로 또는 표 좌표
- 예상 기존값
- 확정 수정값
- confidence=`exact_source`

예상 기존값이 실제 DB와 다르면 적용을 중단한다. 이 조건은 다른 변경이나 잘못된 문항에 교정이 적용되는 것을 방지한다.

2022년 3회 해사영어 3번은 원본 PDF에 따라 발문과 `<보기>` 전체를 source-confirmed repair로 복원한다. 표의 rows와 cells는 동일한 정확한 텍스트를 갖게 한다.

## 활성 DB 전수 교정 흐름

각 DB를 다음 순서로 독립 처리한다.

1. 읽기 전용 전수 감사 및 기준선 보고서 생성
2. 자동교정 후보와 원문 확인 후보 분리
3. 원문 확정 repair registry 결합
4. 원본 DB 백업
5. 별도 staging 복사본에 트랜잭션 적용
6. rows/cells 동기화 및 변경 원장 생성
7. SQLite integrity check, foreign key check, 스키마 검증
8. 전 문항 품질 게이트 재검사
9. mounted repository 검색·조회 smoke test
10. 모든 검증 통과 시에만 원본 DB를 원자적으로 교체

한 DB에서 실패해도 이미 교체된 다른 DB와 상태가 갈리지 않도록 최종 교체 전 네 DB의 staging 검증을 모두 완료한다. 실제 교체는 각 원본의 복구 가능한 백업이 존재하는 상태에서 수행하고, 교체 실패 시 원본을 유지한다.

## 실패 처리

- 원본 PDF가 없거나 페이지를 찾지 못하면 자동수정하지 않는다.
- 여러 수정안이 가능한 OCR은 자동수정하지 않는다.
- 예상 기존값 불일치, invalid JSON, DB 무결성 실패, 품질 게이트 잔여 오류는 배포 차단 사유이다.
- 실패 항목은 검토 보고서에 남기며 성공 항목과 섞어 조용히 적용하지 않는다.
- dry-run은 실제 적용과 동일한 검사 및 staging 변경을 수행하되 원본 DB를 교체하지 않는다.

## 보고서

실행 결과는 기계 판독 JSON과 사람이 검토할 Markdown으로 생성한다.

- DB별 검사 문항·선지·표 셀·공통 지문 수
- 자동교정 수와 규칙별 분포
- source-confirmed 교정 수
- 차단 및 미확정 후보 수
- 필드별 before/after
- rows/cells 불일치
- 원문 경로와 페이지
- 무결성 및 smoke test 결과
- 적용 여부와 백업 경로

## 테스트

테스트는 실패 재현부터 작성한다.

- 2022년 3회 해사영어 3번의 손상된 발문과 표 셀을 재현하고 원문대로 복원한다.
- 같은 OCR 오기가 일반 발문, 일반 선지, question 표, choice 표에 있을 때 모두 탐지된다.
- 공통 지문의 OCR 손상도 탐지된다.
- rows와 cells가 다르면 구조 오류로 차단된다.
- 모호한 후보는 변경되지 않고 `blocked_quality`로 보고된다.
- invalid format JSON은 무시되지 않고 차단된다.
- source-confirmed repair는 예상 기존값이 다르면 전체 트랜잭션을 롤백한다.
- 네 DB staging 검증 중 하나라도 실패하면 실제 DB 교체를 시작하지 않는다.
- DB 무결성, mounted 조회 및 검색이 교정 후 유지된다.
- 전체 pytest 스위트가 통과한다.

## 완료 기준

- 신규 파싱 경로가 모든 rich-text 표면을 정규화하고 검사한다.
- 기존 DB 감사가 question/choice format JSON과 공통 지문을 빠짐없이 포함한다.
- 이미지 사례가 원문대로 교정되고 재파싱 시 재발하지 않는다.
- 활성 DB 네 개의 dry-run 및 실제 적용 보고서가 생성된다.
- 미확정 후보가 자동수정되지 않는다.
- 적용된 DB가 무결성, 스키마, 품질 게이트, mounted smoke test를 통과한다.
- 과거 백업과 outputs 산출물은 변경되지 않는다.
