<script lang="ts">
	import { onMount } from 'svelte';
	import type { TimelineResponse, TimelineEntry } from '$lib/api/types';
	import { Activity } from 'lucide-svelte';

	let { fetchData, refreshKey = 0 }: { fetchData: () => Promise<TimelineResponse>; refreshKey?: number } = $props();

	let data: TimelineResponse | null = $state(null);
	let loading = $state(true);
	let refreshTimer: ReturnType<typeof setInterval> | null = null;
	let tick = $state(0);
	let mounted = $state(false);

	async function load() {
		try {
			data = await fetchData();
		} catch {
			// best-effort
		}
		tick++;
		loading = false;
	}

	onMount(() => {
		load();
		mounted = true;
		refreshTimer = setInterval(load, 30000);
		return () => {
			if (refreshTimer) clearInterval(refreshTimer);
		};
	});

	// Auto-refresh when refreshKey changes (after a run completes)
	$effect(() => {
		const _key = refreshKey;
		if (mounted && _key > 0) {
			load();
		}
	});

	// --- Gantt layout ---

	const HOUR_MS = 3600000;
	const MIN_RANGE_MS = HOUR_MS; // never zoom tighter than 1 hour
	const MIN_BAR_PX = 6;

	// Reactive time range -- auto-zoomed to fit actual data with 10% padding on each side
	const now = $derived.by(() => { const _ = tick; return Date.now(); });

	const timeRange = $derived.by(() => {
		if (!data || data.entries.length === 0) {
			return { start: now - 24 * HOUR_MS, end: now, span: 24 * HOUR_MS };
		}
		let earliest = Infinity;
		let latest = -Infinity;
		for (const e of data.entries) {
			const s = new Date(e.start_time).getTime();
			const end = new Date(e.end_time).getTime();
			if (s < earliest) earliest = s;
			if (end > latest) latest = end;
		}
		// Ensure latest reaches at least "now" so the chart feels current
		if (latest < now) latest = now;
		const dataSpan = latest - earliest;
		const padded = Math.max(MIN_RANGE_MS, dataSpan * 1.2);
		const padding = (padded - dataSpan) / 2;
		const start = earliest - padding;
		const end = latest + padding;
		return { start, end, span: end - start };
	});

	const rangeStart = $derived(timeRange.start);
	const rangeSpan = $derived(timeRange.span);

	// Assign swim lanes by overlap detection
	function assignLanes(entries: TimelineEntry[]): { entry: TimelineEntry; lane: number }[] {
		const laneEnds: number[] = [];
		return entries.map((entry) => {
			const start = new Date(entry.start_time).getTime();
			const end = new Date(entry.end_time).getTime();
			let lane = laneEnds.findIndex((e) => e <= start);
			if (lane === -1) {
				lane = laneEnds.length;
				laneEnds.push(end);
			} else {
				laneEnds[lane] = end;
			}
			return { entry, lane };
		});
	}

	const laneData = $derived(data ? assignLanes(data.entries) : []);
	const maxLane = $derived(laneData.length > 0 ? Math.max(...laneData.map((d) => d.lane)) : 0);
	const laneCount = $derived(Math.max(1, maxLane + 1));
	const LANE_H = 32;

	// Adaptive hour markers -- pick interval so we get 4-8 labels
	const markerStep = $derived.by(() => {
		const hours = rangeSpan / HOUR_MS;
		if (hours <= 2) return HOUR_MS / 4;       // 15min
		if (hours <= 6) return HOUR_MS / 2;        // 30min
		if (hours <= 12) return HOUR_MS;            // 1h
		return HOUR_MS * 3;                         // 3h
	});

	function formatMarkerLabel(d: Date): string {
		const h = d.getHours().toString().padStart(2, '0');
		const m = d.getMinutes().toString().padStart(2, '0');
		return m === '00' ? `${h}:00` : `${h}:${m}`;
	}

	const hourMarkers = $derived.by(() => {
		const markers: { label: string; left: number }[] = [];
		const step = markerStep;
		// Round rangeStart up to next step boundary
		const firstMs = Math.ceil(rangeStart / step) * step;

		for (let t = firstMs; t < rangeStart + rangeSpan; t += step) {
			const d = new Date(t);
			const left = ((t - rangeStart) / rangeSpan) * 100;
			markers.push({ label: formatMarkerLabel(d), left });
		}
		return markers;
	});

	function formatDuration(ms: number): string {
		if (ms < 1000) return `${ms}ms`;
		if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
		return `${(ms / 60000).toFixed(1)}m`;
	}

	function formatCost(usd: number): string {
		if (usd === 0) return '$0';
		if (usd < 0.01) return `$${usd.toFixed(4)}`;
		return `$${usd.toFixed(2)}`;
	}

	function formatTrigger(type: string | null): string {
		if (!type) return 'manual';
		return type.replace(/_/g, ' ');
	}
</script>

<div class="flex flex-col gap-4">
	{#if loading}
		<div class="flex h-48 items-center justify-center">
			<span class="text-[13px] text-fg-faint">Loading timeline...</span>
		</div>
	{:else if !data || data.entries.length === 0}
		<div class="flex h-48 flex-col items-center justify-center gap-2">
			<Activity size={20} class="text-fg-faint" />
			<span class="text-[13px] text-fg-faint">No runs in the last 24 hours</span>
		</div>
	{:else}
		<!-- Stats strip -->
		<div class="flex items-center divide-x divide-edge-subtle border border-edge bg-surface-1">
			<div class="px-4 py-2">
				<div class="metric-label">runs</div>
				<div class="font-mono text-[18px] font-semibold text-fg" style="font-variant-numeric: tabular-nums">
					{data.stats.total_runs}
				</div>
			</div>
			<div class="px-4 py-2">
				<div class="metric-label">success</div>
				<div class="font-mono text-[18px] font-semibold text-fg" style="font-variant-numeric: tabular-nums">
					{data.stats.success_rate}%
				</div>
			</div>
			<div class="px-4 py-2">
				<div class="metric-label">tokens</div>
				<div class="font-mono text-[18px] font-semibold text-fg" style="font-variant-numeric: tabular-nums">
					{data.stats.total_tokens.toLocaleString()}
				</div>
			</div>
			<div class="px-4 py-2">
				<div class="metric-label">avg</div>
				<div class="font-mono text-[18px] font-semibold text-fg" style="font-variant-numeric: tabular-nums">
					{formatDuration(data.stats.avg_duration_ms)}
				</div>
			</div>
			{#if data.stats.total_cost_usd != null}
				<div class="px-4 py-2">
					<div class="metric-label">cost</div>
					<div class="font-mono text-[18px] font-semibold text-fg" style="font-variant-numeric: tabular-nums">
						{formatCost(data.stats.total_cost_usd)}
					</div>
				</div>
			{/if}
		</div>

		<!-- Gantt chart -->
		<div class="overflow-hidden border border-edge bg-surface-1">
			<!-- Hour markers -->
			<div class="relative h-7 border-b border-edge-subtle px-1">
				{#each hourMarkers as marker}
					<span
						class="absolute top-1.5 font-mono text-[10px] text-fg-faint"
						style="left: clamp(0%, {marker.left}%, 100%); transform: translateX({marker.left < 5 ? '0%' : marker.left > 95 ? '-100%' : '-50%'})"
					>
						{marker.label}
					</span>
				{/each}
			</div>

			<!-- Swim lanes -->
			<div class="relative" style="height: {laneCount * LANE_H + 16}px">
				<!-- Gridlines -->
				{#each hourMarkers as marker}
					<div
						class="absolute top-0 h-full border-l border-edge-ghost"
						style="left: {marker.left}%"
					></div>
				{/each}

				<!-- Bars -->
				{#each laneData as { entry, lane }}
					<div
						class="group absolute h-5 {entry.status === 'success' ? 'bg-ok' : 'bg-fail'}"
						style="left: {Math.max(0, ((new Date(entry.start_time).getTime() - rangeStart) / rangeSpan) * 100)}%; min-width: {MIN_BAR_PX}px; width: {Math.max(0.3, ((new Date(entry.end_time).getTime() - new Date(entry.start_time).getTime()) / rangeSpan) * 100)}%; top: {lane * LANE_H + 8}px"
					>
						<!-- Tooltip on hover -->
						<div class="pointer-events-none absolute bottom-full left-1/2 z-10 mb-1.5 hidden -translate-x-1/2 border border-edge bg-surface-2 px-2.5 py-1.5 text-[11px] text-fg-muted shadow-lg group-hover:block" style="white-space: nowrap">
							<span class="font-mono">{formatTrigger(entry.trigger_type)}</span>
							<span class="mx-1 text-fg-faint">|</span>
							<span class="font-mono">{formatDuration(entry.duration_ms)}</span>
							<span class="mx-1 text-fg-faint">|</span>
							<span class="font-mono">{entry.total_tokens} tok</span>
							{#if entry.cost}
								<span class="mx-1 text-fg-faint">|</span>
								<span class="font-mono">{formatCost(entry.cost.total_cost_usd)}</span>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
