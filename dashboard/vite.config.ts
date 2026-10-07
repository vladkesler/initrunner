import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';
import tailwindcss from '@tailwindcss/vite';
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit({
		preprocess: vitePreprocess(),
		adapter: adapter({
			pages: '../initrunner/dashboard/_static',
			assets: '../initrunner/dashboard/_static',
			fallback: 'index.html',
			precompress: false
		}),
		version: { pollInterval: 0 }
	})],
	server: {
		proxy: {
			'/api': 'http://localhost:8100'
		}
	}
});
