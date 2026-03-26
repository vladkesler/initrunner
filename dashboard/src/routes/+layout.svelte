<script lang="ts">
	import '../app.css';
	import Shell from '$lib/components/layout/Shell.svelte';
	import ToastContainer from '$lib/components/ui/ToastContainer.svelte';

	let { children } = $props();
</script>

<Shell>
	{@render children()}
</Shell>
<ToastContainer />
