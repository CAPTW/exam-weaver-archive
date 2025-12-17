/**
 * Electron 환경 감지 및 API 접근 유틸리티
 */

// Electron 환경 여부 확인
export const isElectron = (): boolean => {
  // window.electronAPI가 존재하면 Electron 환경
  return typeof window !== 'undefined' &&
         'electronAPI' in window &&
         (window as any).electronAPI?.isElectron === true;
};

// Electron API 타입 정의
interface ElectronAPI {
  isElectron: boolean;
  platform: string;
  getAppPath: () => Promise<string>;
  getAppInfo: () => Promise<{
    version: string;
    name: string;
    platform: string;
    arch: string;
    electron: string;
    node: string;
    chrome: string;
  }>;
  readFile: (filePath: string) => Promise<{ success: boolean; content?: string; error?: string }>;
  writeFile: (filePath: string, content: string) => Promise<{ success: boolean; error?: string }>;
  fileExists: (filePath: string) => Promise<boolean>;
}

// Electron API 접근
export const getElectronAPI = (): ElectronAPI | null => {
  if (isElectron()) {
    return (window as any).electronAPI as ElectronAPI;
  }
  return null;
};

// 플랫폼 정보
export const getPlatform = (): string => {
  const api = getElectronAPI();
  if (api) {
    return api.platform;
  }
  // 웹 환경에서는 navigator 사용
  if (typeof navigator !== 'undefined') {
    const platform = navigator.platform.toLowerCase();
    if (platform.includes('win')) return 'win32';
    if (platform.includes('mac')) return 'darwin';
    if (platform.includes('linux')) return 'linux';
  }
  return 'unknown';
};

// 앱 버전 가져오기
export const getAppVersion = async (): Promise<string> => {
  const api = getElectronAPI();
  if (api) {
    const info = await api.getAppInfo();
    return info.version;
  }
  return '1.0.0'; // 웹 버전
};

// 앱 정보 가져오기
export const getAppInfo = async () => {
  const api = getElectronAPI();
  if (api) {
    return await api.getAppInfo();
  }
  return {
    version: '1.0.0',
    name: 'Exam Weaver',
    platform: getPlatform(),
    arch: 'unknown',
    electron: 'N/A',
    node: 'N/A',
    chrome: typeof navigator !== 'undefined' ? navigator.userAgent : 'N/A',
  };
};

// 데스크톱 환경 여부 (Electron 또는 데스크톱 브라우저)
export const isDesktop = (): boolean => {
  if (isElectron()) return true;

  // 모바일 기기 감지
  if (typeof navigator !== 'undefined') {
    const userAgent = navigator.userAgent.toLowerCase();
    const mobileKeywords = ['android', 'iphone', 'ipad', 'ipod', 'mobile'];
    return !mobileKeywords.some(keyword => userAgent.includes(keyword));
  }

  return true;
};
