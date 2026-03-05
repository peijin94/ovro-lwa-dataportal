import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  // App is served under /lwa/ in production (https://ovsa.njit.edu/lwa/)
  // so built asset URLs must start with /lwa/.
  base: '/lwa/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/portal': {
        target: 'http://localhost:5001',
        changeOrigin: true,
      },
    },
  },
})
