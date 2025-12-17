const { contextBridge, ipcRenderer } = require('electron');

// 보안을 위해 제한된 API만 노출
contextBridge.exposeInMainWorld('electronAPI', {
  // 앱 정보
  getAppPath: () => ipcRenderer.invoke('get-app-path'),
  getAppInfo: () => ipcRenderer.invoke('get-app-info'),

  // 파일 시스템 (필요시 사용)
  readFile: (filePath) => ipcRenderer.invoke('read-file', filePath),
  writeFile: (filePath, content) => ipcRenderer.invoke('write-file', filePath, content),
  fileExists: (filePath) => ipcRenderer.invoke('file-exists', filePath),

  // 플랫폼 정보
  platform: process.platform,
  isElectron: true,
});

// 윈도우 로드 완료 시 Electron 환경임을 알림
window.addEventListener('DOMContentLoaded', () => {
  console.log('Exam Weaver - Electron 환경에서 실행 중');
});
