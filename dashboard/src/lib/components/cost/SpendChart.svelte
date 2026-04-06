<script lang="ts">
	import type { DailyCost } from '$lib/api/types';
	import { formatCost } from '$lib/utils/format';

	let { data }: { data: DailyCost[] } = $props();

	let containerWidth = $state(0);
	let hoveredIndex = $state<number | null>(null);
	let tooltipX = $state(0);
	let tooltipY = $state(0);

	const PADDING_LEFT = 52;
	const PADDING_RIGHT = 12;
	const PADDING_TOP = 12;
	const PADDING_BOTTOM = 28;
	const HEIGHT = 200;

	const allNull = $derived(data.every((d) => d.total_cost_usd === null));

	const maxCost = $derived.by(() => {
		const vals = data.map((d) => d.total_cost_usd ?? 0).filter((v) => v > 0);
		if (vals.length === 0) return 1;
		const max = Math.max(...vals);
		// Round up to a clean number for gridlines
		const magnitude = Math.pow(10, Math.floor(Math.log10(max)));
		return Math.ceil(max / magnitude) * magnitude || 1;
	});

	const gridLines = $derived.by(() => {
		const lines: number[] = [];
		const step = maxCost / 4;
		for (let i = 0; i <= 4; i++) {
			lines.push(step * i);
		}
		return lines;
	});

	const chartWidth = $derived(containerWidth - PADDING_LEFT - PADDING_RIGHT);
	const chartHeight = $derived(HEIGHT - PADDING_TOP - PADDING_BOTTOM);

	const barWidth = $derived(data.length > 0 ? Math.max(1, (chartWidth - (data.length - 1) * 2) / data.length) : 0);

	function barX(i: number): number {
		return PADDING_LEFT + i * (barWidth + 2);
	}

	function barHeight(cost: number | null): number {
		if (cost === null || cost === 0) return 1;
		return Math.max(2, (cost / maxCost) * chartHeight);
	}

	function barY(cost: number | null): number {
		return PADDING_TOP + chartHeight - barHeight(cost);
	}

	function gridY(val: number): number {
		if (maxCost === 0) return PADDING_TOP + chartHeight;
		return PADDING_TOP + chartHeight - (val / maxCost) * chartHeight;
	}

	function formatDateLabel(dateStr: string): string {
		const d = new Date(dateStr + 'T00:00:00');
		return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
	}

	function handleBarHover(e: MouseEvent, i: number) {
		hoveredIndex = i;
		const rect = (e.currentTarget as SVGElement).ownerSVGElement?.getBoundingClientRect();
		if (rect) {
			tooltipX = e.clientX - rect.left;
			tooltipY = e.clientY - rect.top - 8;
		}
	}

	function handleBarLeave() {
		hoveredIndex = null;
	}
</script>

<div class="border border-edge bg-surface-1" bind:clientWidth={containerWidth}>
	{#if allNull || data.length === 0}
		<div class="flex items-center justify-center py-16 text-[13px] text-fg-faint">
			No pricing data available
		</div>
	{:else}
		<svg
			width={containerWidth}
			height={HEIGHT}
			class="block"
		>
			<!-- Gridlines + Y labels -->
			{#each gridLines as val}
				<line
					x1={PADDING_LEFT}
					y1={gridY(val)}
					x2={containerWidth - PADDING_RIGHT}
					y2={gridY(val)}
					stroke="var(--color-edge-subtle)"
					stroke-width="1"
				/>
				<text
					x={PADDING_LEFT - 6}
					y={gridY(val) + 3}
					text-anchor="end"
					fill="var(--color-fg-faint)"
					font-family="var(--font-mono)"
					font-size="10"
					style="font-variant-numeric: tabular-nums"
				>
					{formatCost(val)}
				</text>
			{/each}

			<!-- Bars -->
			{#each data as entry, i}
				{@const isHovered = hoveredIndex === i}
				{@const isZero = entry.total_cost_usd === null || entry.total_cost_usd === 0}
				<!-- svelte-ignore a11y_no_static_element_interactions -->
				<rect
					x={barX(i)}
					y={barY(entry.total_cost_usd)}
					width={barWidth}
					height={barHeight(entry.total_cost_usd)}
					fill={isZero ? 'var(--color-edge)' : 'var(--color-accent-primary)'}
					opacity={isZero ? 1 : isHovered ? 1 : 0.3}
					class="transition-opacity duration-150"
					onmouseenter={(e) => handleBarHover(e, i)}
					onmouseleave={handleBarLeave}
				/>
			{/each}

			<!-- X-axis date labels -->
			{#each data as entry, i}
				{@const step = Math.max(1, Math.ceil(data.length / 6))}
				{#if i % step === 0 || i === data.length - 1}
					<text
						x={barX(i) + barWidth / 2}
						y={HEIGHT - 6}
						text-anchor="middle"
						fill="var(--color-fg-faint)"
						font-family="var(--font-mono)"
						font-size="10"
					>
						{formatDateLabel(entry.date)}
					</text>
				{/if}
			{/each}

			<!-- Tooltip -->
			{#if hoveredIndex !== null}
				{@const entry = data[hoveredIndex]}
				{@const tx = Math.min(tooltipX, containerWidth - 140)}
				<foreignObject x={tx} y={Math.max(0, tooltipY - 44)} width="130" height="44">
					<div class="border border-edge bg-surface-2 px-2.5 py-1.5">
						<div class="font-mono text-[11px] text-fg" style="font-variant-numeric: tabular-nums">
							{formatCost(entry.total_cost_usd)}
						</div>
						<div class="font-mono text-[10px] text-fg-faint">
							{formatDateLabel(entry.date)} &middot; {entry.run_count} runs
						</div>
					</div>
				</foreignObject>
			{/if}
		</svg>
	{/if}
</div>
