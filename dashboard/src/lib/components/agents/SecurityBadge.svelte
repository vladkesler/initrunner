<script lang="ts">
	let { level, size = 'md' }: { level: string; size?: 'sm' | 'md' } = $props();

	const colorClasses = $derived.by(() => {
		switch (level) {
			case 'public':
			case 'sandbox':
				return 'border-ok/30 bg-ok/10 text-ok';
			case 'internal':
				return 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary';
			case 'development':
				return 'border-warn/30 bg-warn/10 text-warn';
			case 'default':
				return 'border-edge bg-surface-1 text-fg-faint';
			default:
				return 'border-accent-secondary/30 bg-accent-secondary/10 text-accent-secondary';
		}
	});

	const sizeClasses = $derived(
		size === 'sm' ? 'text-[11px] px-1.5 py-0.5' : 'text-[12px] px-2 py-0.5'
	);
</script>

<span class="inline-flex rounded-full border font-mono {colorClasses} {sizeClasses}">
	{level}
</span>
