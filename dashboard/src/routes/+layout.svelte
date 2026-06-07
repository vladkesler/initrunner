<script lang="ts">
	import '../app.css';
	import { afterNavigate } from '$app/navigation';
	import Shell from '$lib/components/layout/Shell.svelte';
	import ToastContainer from '$lib/components/ui/ToastContainer.svelte';
	import ShortcutOverlay from '$lib/components/ShortcutOverlay.svelte';
	import { capturePageview } from '$lib/telemetry';

	let { children } = $props();

	// Manual SPA pageviews (autocapture/capture_pageview are disabled).
	afterNavigate((nav) => {
		if (nav.to) capturePageview(nav.to.url.pathname);
	});
</script>

<Shell>
	{@render children()}
</Shell>
<ToastContainer />
<ShortcutOverlay />
