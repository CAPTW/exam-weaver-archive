# Mounted 문제 풀이 Repository 연동 설계

## 목표

`문제 풀이` 탭이 활성화된 모든 Mounted DB의 시험·과목·문제를 조회하고, 풀이 기록은 원본 DB를 변경하지 않은 채 writable `user_workspace` Mount에 중앙 저장한다.

## 현재 문제

- `MainWindow`는 `MountedExamRepository`를 `BrowserInterface`에만 주입한다.
- `PracticeInterface`는 생성자에서 단일 `ExamRepository(db_path)`를 직접 만든다.
- Mount 변경 신호는 문제 관리 Repository만 갱신한다.
- 문제 풀이의 세션 생성과 결과 저장은 `_get_connection()`과 로컬 정수 ID를 직접 사용한다.
- Mounted Repository의 시험·과목·문제 ID는 `mount_id::local_id` 형식이므로 기존 직접 SQL 경로와 호환되지 않는다.

## 결정 사항

### 조회 Repository

`PracticeInterface`는 Repository를 생성하지 않고 생성자에서 주입받는다. 주입된 Repository는 다음 공개 동작을 제공한다.

- 시험·연도 필터 목록 조회
- 선택 시험의 과목 목록 조회
- 조건에 맞는 선택지 포함 문제 조회
- 문제가 존재하는 첫 시험 코드 조회
- 풀이 세션 생성
- 풀이 결과 저장

단일 `ExamRepository`와 `MountedExamRepository`가 동일한 공개 동작을 제공하며, UI는 Repository 종류를 검사하거나 내부 연결을 직접 사용하지 않는다.

### 화면 표시

- 단일 DB 시험은 기존과 동일하게 `시험명 (시험코드)`로 표시한다.
- Mounted 시험은 `Mount 라벨 · 시험명 (로컬 시험코드)`로 표시한다.
- ComboBox 데이터에는 namespaced 시험 코드를 저장한다.
- 과목 ComboBox 데이터에도 namespaced 과목 코드를 유지한다.
- 같은 시험명이나 과목명이 여러 DB에 존재해도 Mount 경계가 유지된다.

### Mount 갱신

`MainWindow.refresh_question_repository()`는 새 Repository를 문제 관리와 문제 풀이 탭 모두에 전달한다.

- 설정 화면에 머무는 동안에는 즉시 Repository를 교체하고 시험·과목·연도 목록을 다시 읽는다.
- 풀이 진행 중에는 현재 Repository와 선택된 문제를 유지하고 새 Repository 적용을 제출 또는 초기화 시점까지 보류한다.
- 잘못된 manifest는 기존 단일 DB fallback과 오류 알림 동작을 유지한다.

## 풀이 기록 저장

### 저장 위치

Mounted 문제의 풀이 기록은 `_manual_write_mount()`가 선택하는 writable `user_workspace` Mount에 저장한다. 원본 문제 DB의 문제, 모의고사, 결과 테이블에는 쓰지 않는다.

writable `user_workspace`가 없으면 문제 선택 화면은 사용할 수 있지만 시험 시작 전에 명확한 오류를 표시하고 세션을 만들지 않는다.

### 저장 스키마

사용자 작업 DB에 다음 테이블을 추가한다.

#### `practice_attempts`

- 내부 attempt ID
- 원본 Mount ID와 라벨
- namespaced 시험 코드와 시험명
- 상태(`in_progress`, `completed`)
- 전체 문항 수, 정답 수, 점수, 소요 시간
- 시작·완료 시각

#### `practice_attempt_questions`

- attempt ID와 표시 순서
- namespaced 문제 ID와 과목 ID
- 과목명
- 발문·선지·정답 등 문제 스냅샷 JSON
- 사용자 답안, 정답, 정오 여부

#### `practice_attempt_subject_results`

- attempt ID와 namespaced 과목 ID
- 과목명
- 과목별 전체 문항 수, 정답 수, 점수

세션 생성과 문제 스냅샷 저장은 한 트랜잭션으로 처리한다. 제출 시 attempt 갱신, 문항별 답안, 과목별 결과도 한 트랜잭션으로 저장한다. 중간 실패 시 부분 기록을 남기지 않는다.

### 기존 단일 DB 호환

단일 `ExamRepository`는 기존 `mock_exams`, `mock_exam_questions`, `exam_results` 저장 동작을 유지한다. 다만 SQL은 UI에서 Repository 공개 메서드로 이동하여 두 저장 방식이 같은 UI 호출 경로를 사용하게 한다.

## 오류 처리

- namespaced 시험 코드와 과목 코드가 서로 다른 Mount를 가리키면 문제 조회를 거부한다.
- 선택한 시험 또는 문제의 Mount가 비활성화되면 세션 생성 전에 오류를 표시한다.
- writable `user_workspace`가 없거나 저장 스키마 초기화에 실패하면 원본 DB에 대체 기록하지 않는다.
- 세션 저장 실패 시 문제 풀이 화면으로 전환하지 않는다.
- 제출 저장 실패 시 현재 답안과 결과 화면 상태를 유지하고 재시도 가능한 오류를 표시한다.

## 테스트 전략

### Repository 테스트

- Mounted 시험·과목 목록이 namespaced ID와 Mount 라벨을 보존한다.
- Mounted 문제로 만든 attempt가 `user_workspace`에만 저장된다.
- 원본 Mount의 `mock_exams`, `mock_exam_questions`, `exam_results` 및 문제 데이터가 변경되지 않는다.
- 문항 스냅샷, 답안, 전체·과목별 결과가 정확히 저장된다.
- writable `user_workspace`가 없으면 세션 생성이 실패하고 어떤 DB도 변경되지 않는다.

### UI 테스트

- `PracticeInterface(repository=mounted_repository)`가 여러 Mount의 시험을 드롭다운에 표시한다.
- 시험 변경 시 같은 Mount의 namespaced 과목만 표시한다.
- 선택한 Mounted 시험에서 문제를 추출하고 채점할 수 있다.
- Mount 변경 시 설정 화면의 목록은 즉시 갱신된다.
- 진행 중 Mount 변경은 현재 풀이를 중단하지 않고 다음 초기화 시 적용된다.

### 회귀 테스트

- 기존 단일 DB 문제 풀이와 결과 저장 테스트가 계속 통과한다.
- 실제 `data/domain_dbs/mount_manifest.json`에서 단일 DB 목록보다 많은 Mounted 시험이 문제 풀이 목록에 노출되는지 읽기 전용으로 검증한다.
- 전체 테스트 스위트를 실행한다.

## 완료 조건

- 문제 풀이 시험 드롭다운에서 모든 활성 Mount의 시험을 구분해 선택할 수 있다.
- 선택한 시험의 과목과 문제는 동일한 Mount에서 조회된다.
- Mounted 풀이 결과는 `user_workspace`에 저장되고 원본 DB는 바이트 또는 관련 테이블 기준으로 변하지 않는다.
- Mount 설정 변경이 문제 관리와 문제 풀이 양쪽에 반영된다.
- 기존 단일 DB 풀이 기능과 전체 회귀 테스트가 통과한다.
