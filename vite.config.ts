
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react-swc";
import path from "path";
import { componentTagger } from "lovable-tagger";

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => ({
  // Electron 빌드를 위한 base 설정
  base: './',
  server: {
    host: "::",
    port: 8080,
  },
  plugins: [
    react(),
    mode === 'development' &&
    componentTagger(),
  ].filter(Boolean),
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  optimizeDeps: {
    include: ['pdfjs-dist']
  },
  define: {
    global: 'globalThis'
  },
  worker: {
    format: 'es'
  },
  build: {
    // Electron에서 파일 경로를 올바르게 처리하기 위한 설정
    outDir: 'dist',
    assetsDir: 'assets',
    // 소스맵 생성 (디버깅용)
    sourcemap: mode === 'development',
    rollupOptions: {
      output: {
        // 청크 파일 명명 규칙
        chunkFileNames: 'assets/[name]-[hash].js',
        entryFileNames: 'assets/[name]-[hash].js',
        assetFileNames: 'assets/[name]-[hash].[ext]'
      }
    }
  }
}));
