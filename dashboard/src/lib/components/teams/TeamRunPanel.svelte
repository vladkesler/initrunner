<script lang="ts">
	import { streamTeamRun } from '$lib/api/teams';
	import type { TeamRunResponse, TeamThreadMessage, PersonaStepResponse, ThreadMessage } from '$lib/api/types';
	import ConversationThread from '$lib/components/runs/ConversationThread.svelte';
	import PersonaTrace from './PersonaTrace.svelte';
	import { Play, Square, RotateCcw } from 'lucide-svelte';

	let { teamId, onRunCompleted }: { teamId: string; onRunCompleted?: () => void } = $props();

	let prompt = $state('');
	let messages: TeamThreadMessage[] = $state([]);
	let running = $state(false);
	let controller: AbortController | null = $state(null);
	let requestVersion = $state(0);

	/** Adapt TeamThreadMessage[] to ThreadMessage[] for ConversationThread. */
	const threadMessages = $derived<ThreadMessage[]>(
		messages.map((m) => {
			const base: ThreadMessage = {
				role: m.role,
				content: m.content,
				status: m.status,
				error: m.error
			};
			if (m.result) {
				base.result = {
					tokens_in: m.result.tokens_in,
					tokens_out: m.result.tokens_out,
					duration_ms: m.result.duration_ms,
					tool_calls: m.result.steps.reduce((sum, s) => sum + s.tool_calls, 0),
					tool_call_names: [...new Set(m.result.steps.flatMap((s) => s.tool_call_names))],
					success: m.result.success,
					error: m.result.error
				};
			}
			return base;
		})
	);

	/** Active persona from the last streaming message. */
	const activePersona = $derived.by(() => {
		if (!running || messages.length === 0) return null;
		const last = messages[messages.length - 1];
		if (last.role === 'assistant' && last.status === 'streaming') {
			return last.activePersona ?? null;
		}
		return null;
	});

	function handleRun() {
		if (!prompt.trim() || running) return;

		const currentVersion = requestVersion;
		const userPrompt = prompt.trim();
		prompt = '';

		messages = [
			...messages,
			{ role: 'user', content: userPrompt, status: 'complete' },
			{ role: 'assistant', content: '', status: 'streaming', activePersona: null }
		];

		running = true;
		const assistantIdx = messages.length - 1;

		controller = streamTeamRun(
			teamId,
			{ prompt: userPrompt },
			{
				onPersonaStart(name) {
					if (requestVersion !== currentVersion) return;
					messages[assistantIdx] = {
						...messages[assistantIdx],
						activePersona: name
					};
				},
				onPersonaComplete(_step: PersonaStepResponse) {
					// Progress tracked via persona_start; result has full steps
				},
				onResult(r: TeamRunResponse) {
					if (requestVersion !== currentVersion) return;
					messages[assistantIdx] = {
						...messages[assistantIdx],
						content: r.output,
						status: 'complete',
						activePersona: null,
						result: r
					};
					running = false;
					controller = null;
					onRunCompleted?.();
				},
				onError(error: string) {
					if (requestVersion !== currentVersion) return;
					messages[assistantIdx] = {
						...messages[assistantIdx],
						status: 'error',
						activePersona: null,
						error
					};
					running = false;
					controller = null;
				}
			}
		);
	}

	function handleStop() {
		controller?.abort();
		controller = null;
		running = false;

		const lastIdx = messages.length - 1;
		if (lastIdx >= 0 && messages[lastIdx].role === 'assistant' && messages[lastIdx].status === 'streaming') {
			messages[lastIdx] = { ...messages[lastIdx], status: 'interrupted', activePersona: null };
		}
	}

	function handleNewConversation() {
		controller?.abort();
		controller = null;
		running = false;
		requestVersion++;
		messages = [];
		prompt = '';
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !running) {
			e.preventDefault();
			handleRun();
		}
	}

	const isMac = typeof navigator !== 'undefined' && navigator.platform?.includes('Mac');
	const hasMessages = $derived(messages.length > 0);
</script>

<div class="flex flex-1 flex-col gap-3">
	<!-- Active persona indicator -->
	{#if activePersona}
		<div class="flex items-center gap-2 text-[12px] text-accent-primary">
			<span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-accent-primary"></span>
			Running {activePersona}...
		</div>
	{:else if running}
		<div class="flex items-center gap-2 text-[12px] text-fg-faint">
			<span class="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-fg-faint"></span>
			Starting team run...
		</div>
	{/if}

	<!-- Thread -->
	<ConversationThread
		messages={threadMessages}
		emptyText="Send a prompt to run it through the team"
		assistantLabel="Team"
	>
		{#snippet messageFooter({ msg, index })}
			{@const teamMsg = messages[index]}
			{#if teamMsg?.role === 'assistant' && teamMsg.result?.steps}
				<PersonaTrace steps={teamMsg.result.steps} />
			{/if}
		{/snippet}
	</ConversationThread>

	<!-- Input area -->
	<div class="flex flex-col gap-1.5">
		{#if hasMessages}
			<div class="flex justify-end">
				<button
					class="flex items-center gap-1.5 px-2 py-1 font-mono text-[12px] text-fg-faint transition-colors duration-150 hover:text-fg-muted"
					onclick={handleNewConversation}
				>
					<RotateCcw size={12} />
					New conversation
				</button>
			</div>
		{/if}

		<div class="flex flex-col border border-edge bg-surface-1 transition-[border-color,box-shadow] duration-150 focus-within:border-accent-primary/40 focus-within:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]">
			<textarea
				bind:value={prompt}
				placeholder="Enter a prompt..."
				class="w-full resize-none border-none bg-transparent p-3 font-mono text-[13px] text-fg outline-none placeholder:text-fg-faint"
				style="min-height: 80px"
				onkeydown={handleKeydown}
				disabled={running}
			></textarea>
			<div class="flex items-center justify-between border-t border-edge-subtle px-3 py-1.5">
				<span class="font-mono text-[12px] text-fg-faint">{isMac ? 'Cmd' : 'Ctrl'}+Enter to run</span>
				{#if running}
					<button
						class="flex h-7 w-7 items-center justify-center rounded-full border border-edge bg-surface-2 text-fail transition-[border-color,background-color] duration-150 hover:border-fail/40 hover:bg-fail/5"
						onclick={handleStop}
						aria-label="Stop"
					>
						<Square size={14} fill="currentColor" />
					</button>
				{:else}
					<button
						class="flex h-7 w-7 items-center justify-center rounded-full border border-edge bg-surface-2 text-accent-primary transition-[border-color,background-color] duration-150 hover:border-accent-primary/40 hover:bg-accent-primary/5 disabled:pointer-events-none disabled:opacity-30"
						onclick={handleRun}
						disabled={!prompt.trim()}
						aria-label="Run"
					>
						<Play size={14} fill="currentColor" />
					</button>
				{/if}
			</div>
		</div>
	</div>
</div>
