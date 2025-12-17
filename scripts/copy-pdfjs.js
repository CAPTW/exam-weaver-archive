/**
 * PDF.js Worker 파일 자동 복사 스크립트
 * npm install 후 자동으로 실행되어 필요한 PDF.js 파일을 복사합니다.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, '..');

// 소스 및 대상 디렉토리
const nodeModulesPath = path.join(rootDir, 'node_modules', 'pdfjs-dist');
const publicPdfjsPath = path.join(rootDir, 'public', 'pdfjs');
const distPdfjsPath = path.join(rootDir, 'dist', 'pdfjs');

// 필수 파일 목록
const requiredFiles = [
  { src: 'build/pdf.worker.min.mjs', dest: 'pdf.worker.min.mjs' },
  { src: 'build/pdf.worker.mjs', dest: 'pdf.worker.mjs' },
];

// 선택적 디렉토리 (CMap, 폰트 등)
const optionalDirs = [
  { src: 'cmaps', dest: 'cmaps' },
  { src: 'standard_fonts', dest: 'standard_fonts' },
];

/**
 * 디렉토리 생성 (재귀적)
 */
function ensureDir(dirPath) {
  if (!fs.existsSync(dirPath)) {
    fs.mkdirSync(dirPath, { recursive: true });
    console.log(`✓ 디렉토리 생성: ${dirPath}`);
  }
}

/**
 * 파일 복사
 */
function copyFile(src, dest) {
  if (fs.existsSync(src)) {
    ensureDir(path.dirname(dest));
    fs.copyFileSync(src, dest);
    console.log(`✓ 파일 복사: ${path.basename(src)}`);
    return true;
  }
  return false;
}

/**
 * 디렉토리 재귀 복사
 */
function copyDir(src, dest) {
  if (!fs.existsSync(src)) {
    console.log(`⚠ 소스 디렉토리 없음: ${src}`);
    return false;
  }

  ensureDir(dest);
  const entries = fs.readdirSync(src, { withFileTypes: true });

  for (const entry of entries) {
    const srcPath = path.join(src, entry.name);
    const destPath = path.join(dest, entry.name);

    if (entry.isDirectory()) {
      copyDir(srcPath, destPath);
    } else {
      fs.copyFileSync(srcPath, destPath);
    }
  }

  console.log(`✓ 디렉토리 복사: ${path.basename(src)}`);
  return true;
}

/**
 * 메인 실행 함수
 */
function main() {
  console.log('\n📦 PDF.js 파일 복사 시작...\n');

  // node_modules 확인
  if (!fs.existsSync(nodeModulesPath)) {
    console.log('⚠ pdfjs-dist가 설치되지 않았습니다. npm install을 먼저 실행하세요.');
    process.exit(0); // postinstall 시 실패하지 않도록
  }

  // public/pdfjs 디렉토리에 복사
  ensureDir(publicPdfjsPath);

  // 필수 파일 복사
  let copied = 0;
  for (const file of requiredFiles) {
    const srcPath = path.join(nodeModulesPath, file.src);
    const destPath = path.join(publicPdfjsPath, file.dest);
    if (copyFile(srcPath, destPath)) {
      copied++;
    }
  }

  // 선택적 디렉토리 복사
  for (const dir of optionalDirs) {
    const srcPath = path.join(nodeModulesPath, dir.src);
    const destPath = path.join(publicPdfjsPath, dir.dest);
    copyDir(srcPath, destPath);
  }

  // dist 디렉토리가 있으면 거기에도 복사
  if (fs.existsSync(path.join(rootDir, 'dist'))) {
    ensureDir(distPdfjsPath);

    for (const file of requiredFiles) {
      const srcPath = path.join(nodeModulesPath, file.src);
      const destPath = path.join(distPdfjsPath, file.dest);
      copyFile(srcPath, destPath);
    }

    for (const dir of optionalDirs) {
      const srcPath = path.join(nodeModulesPath, dir.src);
      const destPath = path.join(distPdfjsPath, dir.dest);
      copyDir(srcPath, destPath);
    }
  }

  console.log(`\n✅ PDF.js 파일 복사 완료! (${copied}개 파일)\n`);
}

main();
