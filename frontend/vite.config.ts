import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// Default API port of the REST server (uvicorn --port 8080).
export const DEFAULT_BACKEND_API_URL = 'http://localhost:8080'

// Empty prefix loads every variable, including the BFF's BACKEND_API_URL from
// .env, which the browser bundle never sees.
export const resolveBackendApiUrl = (mode: string): string =>
  loadEnv(mode, __dirname, '').BACKEND_API_URL || DEFAULT_BACKEND_API_URL

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react()],
  // Always use /ui/ as base path for both dev and production
  base: '/ui/',
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@components': path.resolve(__dirname, './src/components'),
      '@pages': path.resolve(__dirname, './src/pages'),
      '@hooks': path.resolve(__dirname, './src/hooks'),
      '@contexts': path.resolve(__dirname, './src/contexts'),
      '@types': path.resolve(__dirname, './src/types'),
      '@config': path.resolve(__dirname, './src/config'),
      // Resolve @carbon-labs/utilities subpath export that esbuild can't follow
      '@carbon-labs/utilities/usePrefix': path.resolve(
        __dirname,
        './node_modules/@carbon-labs/utilities/es/usePrefix.js'
      ),
    },
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    // es2022 is required for top-level await used in main.tsx (loadMessages)
    target: 'es2022',
  },
  server: {
    port: 3000,
    open: false,
    proxy: {
      // Proxy all /api/* requests to BFF server
      // This handles ALL API endpoints - no need to update for new endpoints
      '/api': {
        target: 'http://localhost:3001',
        changeOrigin: true
      },
      // /auth/* is served by the REST API itself, never by the BFF.
      // The path is kept as is so the browser origin matches the session cookie.
      '/auth': {
        target: resolveBackendApiUrl(mode),
        changeOrigin: true
      }
    }
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    css: false,
    pool: 'threads',
    alias: {
      '@': path.resolve(__dirname, './src'),
      '@components': path.resolve(__dirname, './src/components'),
      '@pages': path.resolve(__dirname, './src/pages'),
      '@hooks': path.resolve(__dirname, './src/hooks'),
      '@contexts': path.resolve(__dirname, './src/contexts'),
      '@types': path.resolve(__dirname, './src/types'),
      '@config': path.resolve(__dirname, './src/config'),
    },
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/main.tsx',
        'src/vite-env.d.ts',
        'src/**/*.d.ts',
        'src/**/*.module.scss',
        'src/types/**',
        'src/data/**',
        'src/lib/sampleFlowNodes.json',
      ],
      // Global thresholds enforce overall app health.
      // Per-file 60% line coverage is enforced per-PR via
      // scripts/check_pr_coverage_frontend.sh (reads lcov.info from this run).
      thresholds: {
        lines: 80,
        statements: 80,
        functions: 80,
        branches: 75,
      },
    },
  },
}))
