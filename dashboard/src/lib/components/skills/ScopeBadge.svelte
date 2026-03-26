<script lang="ts">
	let { scope, size = 'md' }: { scope: string; size?: 'sm' | 'md' } = $props();

	const label = $derived(scope === 'role-local' ? 'role-local' : scope);

	const colorClasses = $derived.by(() => {
		switch (scope) {
			case 'role-local':
				return 'border-accent-secondary/30 bg-accent-secondary/10 text-accent-secondary';
			case 'project':
				return 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary';
			case 'extra':
				return 'border-warn/30 bg-warn/10 text-warn';
			default:
				return 'border-edge bg-surface-1 text-fg-faint';
		}
	});

	const sizeClasses = $derived(
		size === 'sm' ? 'text-[11px] px-1.5 py-0.5' : 'text-[12px] px-2 py-0.5'
	);
</script>

<span class="inline-flex rounded-full border font-mono {colorClasses} {sizeClasses}">
	{label}
</span>
