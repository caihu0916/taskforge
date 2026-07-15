import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'node:path'

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  esbuild: {
    drop: mode === 'production' ? ['console', 'debugger'] : [],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
      '@tauri-apps/api/core': path.resolve(__dirname, 'src/lib/tauri-mock.ts'),
      '@tauri-apps/api/event': path.resolve(__dirname, 'src/lib/tauri-event-mock.ts'),
    },
  },
  css: {},
  optimizeDeps: {
    include: [
      'antd',
      'antd/es/locale/zh_CN',
      'antd/es/locale/en_US',
      'lucide-react',
      'shiki',
      'recharts',
      'react-markdown',
      'react-virtuoso',
      'pixi.js',
      'dayjs',
      'dayjs/plugin/relativeTime',
      'dayjs/locale/zh-cn',
      'zustand',
      'ky',
      'i18next',
      'react-i18next',
      'react-router-dom',
      'zustand/middleware',
      'marked',
      'dompurify',
    ],
  },
  server: {
    port: 3000,
    strictPort: true,
    hmr: { port: 3000 },
    warmup: {
      clientFiles: [
        './src/main.tsx',
        './src/app/router.tsx',
        './src/stores/auth.ts',
        './src/lib/api.ts',
      ],
    },
    headers: {
      'Cache-Control': 'no-store, no-cache, must-revalidate',
      'Pragma': 'no-cache',
    },
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        configure: (proxy) => {
          proxy.on('proxyRes', (proxyRes) => {
            if (proxyRes.headers['content-type']?.includes('text/event-stream')) {
              proxyRes.headers['cache-control'] = 'no-cache'
              proxyRes.headers['x-accel-buffering'] = 'no'
            }
          })
        },
      },
      '/.well-known': 'http://localhost:8001',
      '/ws': { target: 'ws://localhost:8001', ws: true },
      '/health': 'http://localhost:8001',
    },
  },
  build: {
    outDir: 'dist2',
    sourcemap: false,
    chunkSizeWarningLimit: 600,
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          'react-vendor': ['react', 'react-dom', 'react-router-dom'],
          'lucide': ['lucide-react'],
          'charts': ['recharts'],
          'antd-vendor': ['antd'],
        },
      },
    },
  },
}))
