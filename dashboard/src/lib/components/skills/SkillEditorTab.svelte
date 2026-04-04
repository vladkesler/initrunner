<script lang="ts">
	import { onMount } from 'svelte';
	import { saveSkillContent } from '$lib/api/skills';
	import { Copy, Check, AlertCircle, AlertTriangle, Save, RotateCcw } from 'lucide-svelte';

	let {
		skillId,
		content: initialContent,
		path,
		skillName,
		onSaved
	}: {
		skillId: string;
		content: string;
		path: string;
		skillName: string;
		onSaved?: () => void;
	} = $props();

	let text = $state('');
	let saving = $state(false);
	let saveSuccess = $state(false);
	let saveError = $state<string | null>(null);
	let copied = $state(false);
	let nameWarning = $state(false);
	let saveIssues = $state<string[]>([]);

	const hasChanges = $derived(text !== initialContent);
	const canSave = $derived(hasChanges && !saving);
	const filename = $derived(path.substring(path.lastIndexOf('/') + 1));

	onMount(() => {
		text = initialContent;
	});

	function onInput() {
		saveSuccess = false;
		saveError = null;
		saveIssues = [];

		// Check for name change in frontmatter
		const match = text.match(/^---[\s\S]*?^name:\s*(.+)$/m);
		const parsedName = match?.[1]?.trim();
		nameWarning = !!parsedName && parsedName !== skillName;
	}

	async function handleSave() {
		saving = true;
		saveError = null;
		saveSuccess = false;
		saveIssues = [];
		try {
			const result = await saveSkillContent(skillId, text);
			if (result.valid) {
				saveSuccess = true;
				saveIssues = result.issues; // warnings
				onSaved?.();
			} else {
				saveIssues = result.issues;
				saveError = 'Validation failed';
			}
		} catch (err) {
			saveError = err instanceof Error ? err.message : 'Save failed';
		} finally {
			saving = false;
		}
	}

	function handleReset() {
		text = initialContent;
		nameWarning = false;
		saveSuccess = false;
		saveError = null;
		saveIssues = [];
	}

	async function copyContent() {
		await navigator.clipboard.writeText(text);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}
</script>

<div class="space-y-3">
	<!-- Toolbar -->
	<div class="flex items-center gap-2">
		<button
			class="inline-flex items-center gap-1.5 rounded-[2px] bg-accent-primary px-4 py-1.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover disabled:opacity-40"
			onclick={handleSave}
			disabled={!canSave}
		>
			<Save size={13} />
			{saving ? 'Saving...' : 'Save'}
		</button>

		<button
			class="inline-flex items-center gap-1.5 rounded-full border border-edge px-4 py-1.5 text-[13px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/20 hover:bg-surface-2 hover:text-fg-muted disabled:opacity-40"
			onclick={handleReset}
			disabled={!hasChanges}
		>
			<RotateCcw size={12} />
			Reset
		</button>

		<button
			class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
			onclick={copyContent}
			aria-label="Copy content"
		>
			{#if copied}
				<Check size={14} class="text-ok" />
				<span class="text-ok">Copied</span>
			{:else}
				<Copy size={14} />
				<span>Copy</span>
			{/if}
		</button>

		<span class="ml-auto font-mono text-[12px] text-fg-faint">{filename}</span>
	</div>

	<!-- Success / error messages -->
	{#if saveSuccess}
		<div class="flex items-center gap-1.5 text-[13px] text-ok">
			<Check size={14} />
			Saved successfully
		</div>
	{/if}
	{#if saveError}
		<div class="flex items-center gap-1.5 text-[13px] text-fail">
			<AlertCircle size={14} />
			{saveError}
		</div>
	{/if}

	<!-- Name change warning -->
	{#if nameWarning}
		<div class="flex items-start gap-2 border-l-2 border-l-warn bg-warn/5 px-3 py-2">
			<AlertTriangle size={14} class="mt-0.5 shrink-0 text-warn" />
			<p class="text-[13px] text-fg-muted">
				Changing the skill name may break agents that reference it.
			</p>
		</div>
	{/if}

	<!-- Editor -->
	<textarea
		bind:value={text}
		oninput={onInput}
		class="min-h-[500px] w-full resize-y border border-edge bg-surface-0 p-4 font-mono text-[13px] leading-relaxed text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
		spellcheck="false"
	></textarea>

	<!-- Validation issues -->
	{#if saveIssues.length > 0}
		<div class="space-y-1">
			{#each saveIssues as issue}
				<div class="flex items-start gap-2 font-mono text-[13px]">
					{#if saveError}
						<AlertCircle size={14} class="mt-0.5 shrink-0 text-fail" />
						<span class="text-fail">{issue}</span>
					{:else}
						<AlertTriangle size={14} class="mt-0.5 shrink-0 text-warn" />
						<span class="text-warn">{issue}</span>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
