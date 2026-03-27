<script lang="ts">
	import { createAvatar } from '@dicebear/core';
	import * as rings from '@dicebear/rings';

	let { seed, size = 36, spinning = false }: { seed: string; size?: number; spinning?: boolean } = $props();

	// Constrained palette from Electric Charcoal design system
	const RING_COLORS = [
		'c8ff00', // accent-primary (lime)
		'00e5ff', // accent-secondary (cyan)
		'34d399', // ok (green)
		'a78bfa', // violet (complements lime)
		'60a5fa', // info (blue)
		'fbbf24' // warn (amber)
	];

	const svg = $derived(
		createAvatar(rings, {
			seed,
			size,
			backgroundColor: ['0e0e10'],
			ringColor: RING_COLORS
		}).toString()
	);
</script>

<div
	class="shrink-0 overflow-hidden rounded-full"
	class:animate-avatar-spin={spinning}
	style="width: {size}px; height: {size}px"
	aria-hidden="true"
>
	{@html svg}
</div>

<style>
	@keyframes avatar-spin {
		from { transform: rotate(0deg); }
		to { transform: rotate(360deg); }
	}
	.animate-avatar-spin {
		animation: avatar-spin 3s linear infinite;
	}
	@media (prefers-reduced-motion: reduce) {
		.animate-avatar-spin {
			animation: none;
		}
	}
</style>
