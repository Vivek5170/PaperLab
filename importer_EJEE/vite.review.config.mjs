// External Vite config: no edit to the downloaded PaperLab frontend.
// Dynamic URLs keep Vite from rebundling the plugin beside this external config.
const { sveltekit } = await import(new URL('./reference/PaperLab/frontend/node_modules/@sveltejs/kit/src/exports/vite/index.js', import.meta.url).href);
export default {
  plugins: [sveltekit()],
  server: { host: '127.0.0.1', port: 5183, strictPort: true,
    proxy: { '/api': { target: 'http://127.0.0.1:8011', changeOrigin: true } } }
};
