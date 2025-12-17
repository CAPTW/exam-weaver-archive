# Exam Weaver - Windows 11 설치 및 실행 가이드

## 개요

Exam Weaver는 시험 문제를 관리하고 생성하는 데스크톱 애플리케이션입니다.
Windows 11에서 별도의 복잡한 설치 과정 없이 바로 사용할 수 있습니다.

## 빠른 시작 (Portable 버전)

### 방법 1: 빌드된 실행 파일 사용 (권장)

1. `release` 폴더에서 `Exam Weaver-*-Portable.exe` 파일을 찾습니다.
2. 더블 클릭하여 실행합니다.
3. 별도 설치 없이 바로 사용 가능합니다.

### 방법 2: 직접 빌드

#### 사전 요구사항

- **Node.js LTS** (v18 이상): https://nodejs.org/

#### 빌드 단계

**방법 A: 배치 파일 사용 (가장 간단)**

```
build-windows.bat
```
더블 클릭하면 자동으로 빌드됩니다.

**방법 B: PowerShell 사용**

```powershell
powershell -ExecutionPolicy Bypass -File build-windows.ps1
```

**방법 C: 수동 빌드**

```bash
# 1. 의존성 설치
npm install

# 2. 웹 앱 빌드
npm run build

# 3. PDF.js 파일 복사
npm run copy-pdfjs

# 4. Portable 앱 빌드
npm run electron:build:portable
```

빌드가 완료되면 `release` 폴더에 실행 파일이 생성됩니다.

## 설치 프로그램 (Installer) 빌드

설치 프로그램을 만들려면:

```bash
npm run electron:build
```

이 명령은 다음 파일들을 생성합니다:
- `Exam Weaver-*-x64.exe` - 설치 프로그램
- `Exam Weaver-*-Portable.exe` - 포터블 버전

## 개발 모드 실행

개발 중에 실시간으로 변경사항을 확인하려면:

```bash
# Vite 개발 서버 + Electron 동시 실행
npm run electron:dev
```

## 주요 기능

- **PDF 문제 파싱**: PDF 파일에서 시험 문제를 자동으로 추출
- **문제 은행 관리**: 과목별, 난이도별 문제 분류 및 검색
- **시험지 생성**: 맞춤형 시험지 자동 생성
- **데이터 영구 저장**: 모든 데이터는 로컬에 안전하게 저장

## 데이터 저장 위치

- **Windows**: `%APPDATA%\exam-weaver`
- 또는 브라우저 LocalStorage에 저장 (웹 모드)

## 문제 해결

### "Node.js가 설치되어 있지 않습니다" 오류

1. https://nodejs.org/ 에서 Node.js LTS 버전 다운로드
2. 설치 후 명령 프롬프트를 다시 열고 빌드 실행

### PDF 파싱이 작동하지 않음

1. `public/pdfjs` 폴더에 worker 파일이 있는지 확인
2. 없다면 `npm run copy-pdfjs` 실행

### 앱이 실행되지 않음

1. Windows Defender나 백신에서 차단되었는지 확인
2. "자세한 정보" → "실행" 클릭

## 프로젝트 구조

```
exam-weaver/
├── electron/           # Electron 메인 프로세스
│   ├── main.js         # 메인 프로세스 진입점
│   └── preload.js      # preload 스크립트
├── src/                # React 소스 코드
├── public/             # 정적 파일
│   └── pdfjs/          # PDF.js worker 파일
├── build/              # 빌드 리소스 (아이콘 등)
├── scripts/            # 빌드 스크립트
├── release/            # 빌드 출력 (생성됨)
├── build-windows.bat   # Windows 빌드 스크립트
├── build-windows.ps1   # PowerShell 빌드 스크립트
└── electron-builder.json # Electron Builder 설정
```

## 스크립트 명령어

| 명령어 | 설명 |
|--------|------|
| `npm run dev` | Vite 개발 서버 실행 |
| `npm run build` | 웹 앱 빌드 |
| `npm run electron:dev` | Electron 개발 모드 |
| `npm run electron:preview` | Electron 미리보기 |
| `npm run electron:build` | Windows 빌드 (설치 프로그램 + Portable) |
| `npm run electron:build:portable` | Portable 버전만 빌드 |
| `npm run copy-pdfjs` | PDF.js 파일 복사 |

## 라이선스

MIT License
