import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' — GitHub Pages 하위 경로와 Vercel 루트 둘 다에서 동작
export default defineConfig({
  base: './',
  plugins: [react()],
  // 개발용: AI 예상 이미지 서버(server/, uvicorn :8000)로 /api 요청을 넘긴다
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
});
