<script lang="ts">
	const CAPS = [
		{ key: 'tools', label: 'Tools' },
		{ key: 'triggers', label: 'Triggers' },
		{ key: 'ingest', label: 'Ingest' },
		{ key: 'memory', label: 'Memory' },
		{ key: 'sinks', label: 'Sinks' },
		{ key: 'skills', label: 'Skills' },
	] as const;

	let { features, size = 'sm' }: { features: string[]; size?: 'sm' | 'md' } = $props();

	const active = $derived(CAPS.filter((c) => features.includes(c.key)).map((c) => c.label));
</script>

<div
	class="grid grid-cols-2 {size === 'sm' ? 'gap-[2px]' : 'gap-[2px]'}"
	title={active.length > 0 ? active.join(', ') : 'No capabilities'}
	aria-label="Capability glyph: {active.join(', ') || 'none'}"
>
	{#each CAPS as cap}
		<span
			class="{size === 'sm' ? 'h-[6px] w-[6px]' : 'h-[7px] w-[7px]'} {features.includes(cap.key) ? 'bg-accent-primary' : 'bg-accent-primary/15'}"
		></span>
	{/each}
</div>
