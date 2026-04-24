<script lang="ts">
	let { children }: { children: import('svelte').Snippet } = $props();
</script>

<kbd
	class="ml-1 inline-flex h-[18px] items-center rounded-sm border border-edge-subtle bg-surface-2 px-1 font-mono text-[10px] leading-none text-fg-muted"
>
	{@render children()}
</kbd>

<style>
	kbd {
		font-family: 'IBM Plex Mono', monospace;
	}
</style>
