import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

// Dev only: the Python app serves the built UI itself in normal use.
const api = `http://127.0.0.1:${process.env.EJEE_APP_PORT || 8030}`;

export default defineConfig({
	plugins: [sveltekit()],
	server: {
		host: '127.0.0.1',
		port: 5174,
		proxy: {
			// The app refuses cross-origin writes; present the API's own origin.
			'/api': { target: api, changeOrigin: true, headers: { origin: api } }
		}
	}
});
