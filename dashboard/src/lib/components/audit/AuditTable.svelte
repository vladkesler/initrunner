<script lang="ts">
	import type { AuditRecord } from '$lib/api/types';
	import { formatCost } from '$lib/utils/format';

	let {
		records,
		onRowClick,
		hideAgentColumn = false
	}: {
		records: AuditRecord[];
		onRowClick?: (record: AuditRecord) => void;
		hideAgentColumn?: boolean;
	} = $props();

	function formatTime(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
		} catch {
			return ts;
		}
	}

	function formatDate(ts: string): string {
		try {
			const d = new Date(ts);
			return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
		} catch {
			return '';
		}
	}

	function truncate(text: string, len: number): string {
		if (!text) return '\u2014';
		return text.length > len ? text.slice(0, len) + '\u2026' : text;
	}
</script>

{#if records.length === 0}
	<div class="flex items-center justify-center py-16 text-[13px] text-fg-faint">
		No audit records found
	</div>
{:else}
	<table class="w-full">
		<thead>
			<tr class="border-b border-edge bg-surface-05">
				<th class="w-8 px-3 py-2"></th>
				<th class="section-label w-40 px-3 py-2 text-left">Time</th>
				{#if !hideAgentColumn}
					<th class="section-label min-w-[7rem] px-3 py-2 text-left">Agent</th>
				{/if}
				<th class="section-label hidden px-3 py-2 text-left lg:table-cell">Prompt</th>
				<th class="section-label w-20 px-3 py-2 text-right">Tokens</th>
				<th class="section-label w-20 px-3 py-2 text-right">Cost</th>
				<th class="section-label w-24 px-3 py-2 text-right">Duration</th>
				<th class="section-label hidden px-3 py-2 text-left md:table-cell">Model</th>
			</tr>
		</thead>
		<tbody>
			{#each records as record (record.run_id)}
				<tr
					class="border-b border-edge-subtle transition-[background-color] duration-150 hover:bg-surface-1"
					class:cursor-pointer={!!onRowClick}
					onclick={() => onRowClick?.(record)}
					role={onRowClick ? 'button' : undefined}
					tabindex={onRowClick ? 0 : undefined}
					onkeydown={(e) => e.key === 'Enter' && onRowClick?.(record)}
				>
					<td class="w-8 px-3 py-2">
						<span
							class="status-dot"
							class:bg-ok={record.success}
							class:bg-fail={!record.success}
						></span>
					</td>
					<td class="w-40 px-3 py-2 font-mono text-[13px] text-fg-faint">
						<span class="text-fg-muted">{formatDate(record.timestamp)}</span>
						{' '}{formatTime(record.timestamp)}
					</td>
					{#if !hideAgentColumn}
						<td class="min-w-[7rem] px-3 py-2 font-mono text-[13px] text-fg-muted">
							{record.agent_name}
						</td>
					{/if}
					<td class="hidden max-w-xs truncate px-3 py-2 font-mono text-[13px] text-fg-faint lg:table-cell">
						{truncate(record.user_prompt, 40)}
					</td>
					<td class="w-20 px-3 py-2 text-right font-mono text-[13px] text-fg-faint" style="font-variant-numeric: tabular-nums">
						{record.total_tokens.toLocaleString()}
					</td>
					<td class="w-20 px-3 py-2 text-right font-mono text-[13px] text-fg-faint" style="font-variant-numeric: tabular-nums">
						{formatCost(record.cost_usd)}
					</td>
					<td class="w-24 px-3 py-2 text-right font-mono text-[13px] text-fg-faint" style="font-variant-numeric: tabular-nums">
						{record.duration_ms}ms
					</td>
					<td class="hidden max-w-[10rem] truncate px-3 py-2 font-mono text-[13px] text-fg-faint md:table-cell">
						{record.model}
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}
