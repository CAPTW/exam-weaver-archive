Exam Generator 실행 안내

이 폴더에서 아래 파일을 더블클릭하면 됩니다.

1. Run_Latest_App.bat
   - 최신 코드가 즉시 반영된 개발용 앱을 실행합니다.
   - Codex가 로직을 수정한 직후 빠르게 확인할 때 사용합니다.
   - .venv 폴더가 이 프로젝트 안에 있어야 합니다.

2. Build_And_Run_Packaged_App.bat
   - 테스트를 먼저 실행합니다.
   - 테스트가 통과하면 최신 코드로 패키징을 다시 만듭니다.
   - 새로 만들어진 dist\ExamGenerator\ExamGenerator.exe를 실행합니다.
   - 프로그래밍을 모르는 사용자가 실제 배포본 기준으로 확인할 때 사용합니다.

권장 사용 방식

- 수정 직후 빠른 확인: Run_Latest_App.bat
- 다른 사용자에게 전달하기 전 확인: Build_And_Run_Packaged_App.bat

Codex 패널

- 이 코드베이스에는 Codex SDK 연결이 포함되어 있습니다.
- requirements.txt의 openai-codex와 ExamGenerator.spec의 openai_codex/codex_cli_bin 번들 설정으로 실행됩니다.
- 개인 인증 파일은 저장소에 포함하지 않습니다.
- 앱에서 Codex > 로그인 버튼을 누르면 각 사용자의 계정으로 Codex 로그인을 진행합니다.
- 로그인 결과는 로컬 런타임 폴더인 data\codex_panel_home 아래에만 저장됩니다.
- 이미 %USERPROFILE%\.codex\auth.json이 있는 사용자는 앱이 해당 인증을 data\codex_panel_home으로 복사해 사용합니다.

주의

- Build_And_Run_Packaged_App.bat은 패키징 과정 때문에 시간이 걸릴 수 있습니다.
- 테스트가 실패하면 패키징은 중단됩니다. 이 경우 개발자에게 오류 화면을 전달하면 됩니다.
