<script lang="ts">
	import { streamTeamRun } from '$lib/api/teams';
	import type { TeamRunResponse, TeamThreadMessage, PersonaStepResponse, ThreadMessage, TeamDetail, ToolEventData } from '$lib/api/types';
	import ConversationThread from '$lib/components/runs/ConversationThread.svelte';
	import ToolActivityPanel from '$lib/components/runs/ToolActivityPanel.svelte';
	import TokenMeter from '$lib/components/runs/TokenMeter.svelte';
	import PersonaTrace from './PersonaTrace.svelte';
	import SeedAvatar from '$lib/components/ui/SeedAvatar.svelte';
	import { Play, Square, RotateCcw } from 'lucide-svelte';

	let { teamId, detail, onRunCompleted }: { teamId: string; detail: TeamDetail; onRunCompleted?: () => void } = $props();

	let prompt = $state('');
	let messages: TeamThreadMessage[] = $state([]);
	let running = $state(false);
	let controller: AbortController | null = $state(null);
	let requestVersion = $state(0);
	let toolEvents: ToolEventData[] = $state([]);
	let lastTeamResult: TeamRunResponse | null = $state(null);

	/** Adapt TeamThreadMessage[] to ThreadMessage[] for ConversationThread. */
	const threadMessages = $derived<ThreadMessage[]>(
		messages.map((m) => {
			const isDebateStreaming = debateMode && m.status === 'streaming';
			const base: ThreadMessage = {
				role: m.role,
				content: m.content,
				status: m.status,
				error: m.error,
				identityLabel: m.role === 'user'
					? 'You'
					: isDebateStreaming
						? debateRound
							? `Round ${debateRound}/${detail.debate?.max_rounds ?? '?'} \u00B7 ${debateElapsed}s`
							: `Agents thinking \u00B7 ${debateElapsed}s`
						: (m.activePersona ?? 'Team'),
				avatarSeeds: isDebateStreaming ? debateSeeds : undefined
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

	/** Active persona(s) from the last streaming message. */
	const activePersona = $derived.by(() => {
		if (!running || messages.length === 0) return null;
		const last = messages[messages.length - 1];
		if (last.role === 'assistant' && last.status === 'streaming') {
			return last.activePersona ?? null;
		}
		return null;
	});

	/** All currently-running personas (for debate concurrent display). */
	let activeSet = $state(new Set<string>());
	/** True once we see >1 concurrent personas; stays true until run finishes. */
	let debateMode = $state(false);
	/** Persona base names from team detail (stable, no race condition). */
	const debateSeeds = $derived(
		detail.strategy === 'debate' ? detail.personas.map((p) => p.name) : []
	);
	/** Current debate round parsed from activePersona name. */
	const debateRound = $derived.by(() => {
		if (!activePersona) return null;
		const m = activePersona.match(/\(round (\d+)\)/);
		return m ? parseInt(m[1]) : null;
	});
	let debateStart = $state(0);
	let debateElapsed = $state(0);
	let debateTimer: ReturnType<typeof setInterval> | null = null;

	$effect(() => {
		if (activeSet.size > 1 && !debateMode) {
			debateMode = true;
		}
	});

	$effect(() => {
		if (debateMode && !debateTimer) {
			debateStart = Math.floor(Date.now() / 1000);
			debateElapsed = 0;
			debateTimer = setInterval(() => {
				debateElapsed = Math.floor(Date.now() / 1000) - debateStart;
			}, 1000);
		} else if (!debateMode && debateTimer) {
			clearInterval(debateTimer);
			debateTimer = null;
		}
	});

	function handleRun() {
		if (!prompt.trim() || running) return;

		const currentVersion = requestVersion;
		const userPrompt = prompt.trim();
		prompt = '';
		toolEvents = [];
		lastTeamResult = null;

		messages = [
			...messages,
			{ role: 'user', content: userPrompt, status: 'complete' },
			{ role: 'assistant', content: '', status: 'streaming', activePersona: null }
		];

		running = true;
		activeSet = new Set();
		debateMode = false;
		const assistantIdx = messages.length - 1;

		controller = streamTeamRun(
			teamId,
			{ prompt: userPrompt },
			{
				onPersonaStart(name) {
					if (requestVersion !== currentVersion) return;
					activeSet = new Set([...activeSet, name]);
					messages[assistantIdx] = {
						...messages[assistantIdx],
						activePersona: name
					};
				},
				onPersonaComplete(step: PersonaStepResponse) {
					activeSet = new Set([...activeSet].filter((n) => n !== step.persona_name));
				},
				onToolEvent(data: ToolEventData) {
					if (requestVersion !== currentVersion) return;
					toolEvents = [...toolEvents, data];
				},
				onResult(r: TeamRunResponse) {
					if (requestVersion !== currentVersion) return;
					debateMode = false;
					if (debateTimer) { clearInterval(debateTimer); debateTimer = null; }
					messages[assistantIdx] = {
						...messages[assistantIdx],
						content: r.output,
						status: 'complete',
						activePersona: null,
						result: r
					};
					lastTeamResult = r;
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
		toolEvents = [];
		lastTeamResult = null;
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && !running) {
			e.preventDefault();
			handleRun();
		}
	}

	const isMac = typeof navigator !== 'undefined' && navigator.platform?.includes('Mac');
	const hasMessages = $derived(messages.length > 0);
	const showPanel = $derived(running || toolEvents.length > 0 || lastTeamResult != null);
</script>

<div class="flex flex-1 flex-col gap-3">
	<!-- Active persona indicator (non-debate) -->
	{#if activePersona && !debateMode}
		<div class="flex items-center gap-2 text-[12px] text-accent-primary">
			<span class="inline-block h-1.5 w-1.5 animate-pulse rounded-[2px] bg-accent-primary"></span>
			Running {activePersona}...
		</div>
	{/if}

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

	{#if showPanel}
		<div class="h-48 shrink-0">
			<ToolActivityPanel events={toolEvents} />
		</div>
		<TokenMeter result={lastTeamResult} {running} />
	{/if}

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
