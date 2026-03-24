import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      manifest: {
        name: 'BookCompass',
        short_name: 'BookCompass',
        description: 'Vind boeken op basis van schrijfstijl en thematiek',
        theme_color: '#10466c',
        background_color: '#10466c',
        display: 'standalone',
        orientation: 'portrait',
        icons: [
          { src: '/favicon.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
  },
})
