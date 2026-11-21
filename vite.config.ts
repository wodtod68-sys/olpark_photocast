import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// base './' — GitHub Pages 하위 경로와 Vercel 루트 둘 다에서 동작
export default defineConfig({
  base: './',
  plugins: [react()],
});
