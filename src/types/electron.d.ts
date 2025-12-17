/**
 * Electron API TypeScript 타입 선언
 */

export interface ElectronAppInfo {
  version: string;
  name: string;
  platform: string;
  arch: string;
  electron: string;
  node: string;
  chrome: string;
}

export interface FileOperationResult {
  success: boolean;
  content?: string;
  error?: string;
}

export interface ElectronAPI {
  isElectron: boolean;
  platform: string;
  getAppPath: () => Promise<string>;
  getAppInfo: () => Promise<ElectronAppInfo>;
  readFile: (filePath: string) => Promise<FileOperationResult>;
  writeFile: (filePath: string, content: string) => Promise<FileOperationResult>;
  fileExists: (filePath: string) => Promise<boolean>;
}

declare global {
  interface Window {
    electronAPI?: ElectronAPI;
  }
}

export {};
