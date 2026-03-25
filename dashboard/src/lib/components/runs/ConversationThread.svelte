<script lang="ts">
	import type { ThreadMessage } from '$lib/api/types';
	import type { Snippet } from 'svelte';
	import { OctagonX, CircleStop, Play } from 'lucide-svelte';

	let {
		messages = [],
		emptyText = 'Run an agent to see output here',
		assistantLabel = 'Agent',
		messageFooter
	}: {
		messages?: ThreadMessage[];
		emptyText?: string;
		assistantLabel?: string;
		messageFooter?: Snippet<[{ msg: ThreadMessage; index: number }]>;
	} = $props();

	let containerEl: HTMLDivElement | undefined = $state();

	// Auto-scroll to bottom when messages change or content streams
	$effect(() => {
		// Touch messages array and last message content to trigger on every update
		const _len = messages.length;
		const _last = messages.length > 0 ? messages[messages.length - 1].content : '';
		if (containerEl) {
			containerEl.scrollTop = containerEl.scrollHeight;
		}
	});
</script>

<div
	bind:this={containerEl}
	class="min-h-[200px] max-h-[calc(100dvh-32rem)] overflow-auto px-1"
>
	{#if messages.length === 0}
		<div class="flex h-full min-h-[200px] flex-col items-center justify-center gap-2">
			<Play size={20} class="text-fg-faint" />
			<span class="text-[13px] text-fg-faint">{emptyText}</span>
		</div>
	{:else}
		<div class="flex flex-col gap-5 py-2">
			{#each messages as msg, i (i)}
				{#if msg.role === 'user'}
					<!-- User turn -->
					<div class="flex flex-col gap-1.5">
						<span class="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-fg-faint">You</span>
						<div class="border-l-2 border-accent-primary/30 bg-accent-primary/[0.03] px-4 py-2.5">
							<pre class="select-text cursor-text whitespace-pre-wrap break-words font-mono text-[13px] leading-relaxed text-fg">{msg.content}</pre>
						</div>
					</div>
				{:else}
					<!-- Agent turn -->
					<div class="flex flex-col gap-1.5">
						<span class="font-mono text-[11px] font-medium uppercase tracking-[0.1em] text-fg-faint">{assistantLabel}</span>
						<div
							class="bg-surface-1 px-4 py-3 transition-[border-color,box-shadow] duration-200"
							class:border-l-2={msg.status === 'streaming'}
							class:border-accent-primary={msg.status === 'streaming'}
							class:glow-lime={msg.status === 'streaming'}
						>
							{#if msg.content}
								<div class="select-text cursor-text whitespace-pre-wrap break-words text-[14px] leading-[1.7] text-fg">{msg.content}</div>
							{:else if msg.status === 'streaming'}
								<span class="text-[13px] text-fg-faint">Thinking...</span>
							{/if}

							{#if msg.status === 'streaming'}
								<span class="ml-0.5 inline-block h-[18px] w-[2px] animate-pulse bg-accent-primary align-text-bottom"></span>
							{/if}

							{#if msg.status === 'interrupted'}
								<div class="mt-2 flex items-center gap-1.5 text-[12px] text-fg-faint">
									<CircleStop size={12} />
									Stopped
								</div>
							{/if}

							{#if msg.status === 'error' && msg.error}
								<div class="mt-2 flex items-center gap-1.5 text-[12px] text-fail">
									<OctagonX size={12} />
									{msg.error}
								</div>
							{/if}

							<!-- Per-turn run metadata -->
							{#if msg.result}
								{@const r = msg.result}
								{@const tc = r.tool_calls || r.tool_call_names.length}
								<div class="mt-3 flex flex-wrap items-center gap-3 border-t border-edge-subtle pt-2.5 font-mono text-[11px] text-fg-faint" style="font-variant-numeric: tabular-nums">
									<span>{r.tokens_in.toLocaleString()} in / {r.tokens_out.toLocaleString()} out</span>
									<span>
										{tc} tool{tc !== 1 ? 's' : ''}
										{#if r.tool_call_names.length > 0}
											<span class="text-fg-muted">({r.tool_call_names.join(', ')})</span>
										{/if}
									</span>
									<span>{r.duration_ms.toLocaleString()}ms</span>
									{#if !r.success && r.error}
										<span class="text-fail">{r.error}</span>
									{/if}
								</div>
							{/if}

							{#if messageFooter}
								{@render messageFooter({ msg, index: i })}
							{/if}
						</div>
					</div>
				{/if}
			{/each}
		</div>
	{/if}
</div>
