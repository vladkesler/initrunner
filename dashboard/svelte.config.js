import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({
			pages: '../initrunner/dashboard/_static',
			assets: '../initrunner/dashboard/_static',
			fallback: 'index.html',
			precompress: false
		}),
		alias: {
			$components: 'src/lib/components'
		}
	}
};

export default config;
