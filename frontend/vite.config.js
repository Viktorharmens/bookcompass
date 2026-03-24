import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'Semantische Boekaanbeveler',
        short_name: 'Boeken',
        description: 'Vind boeken op basis van schrijfstijl en thematiek',
        theme_color: '#4a3f6b',
        background_color: '#4a3f6b',
        display: 'standalone',
        orientation: 'portrait',
        icons: [
          { src: '/logo192.png', sizes: '192x192', type: 'image/png', purpose: 'any maskable' },
          { src: '/logo512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
  },
})
