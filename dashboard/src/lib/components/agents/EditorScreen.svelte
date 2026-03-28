<script lang="ts">
	import { onDestroy } from 'svelte';
	import { validateYaml, type ValidationIssue } from '$lib/api/builder';
	import CognitionPanel from './CognitionPanel.svelte';
	import {
		Brain,
		CircleX,
		TriangleAlert,
		Info,
		Loader2
	} from 'lucide-svelte';

	let {
		yamlText = $bindable(''),
		explanation,
		roleDirs,
		selectedDir = $bindable(''),
		filename = $bindable('role.yaml'),
		issues = $bindable<ValidationIssue[]>([]),
		saving,
		saveError,
		showOverwrite,
		onSave,
		onSaveForce,
		onBack,
		toolFuncMap = {}
	}: {
		yamlText: string;
		explanation: string;
		roleDirs: string[];
		selectedDir: string;
		filename: string;
		issues: ValidationIssue[];
		saving: boolean;
		saveError: string | null;
		showOverwrite: boolean;
		onSave: () => void;
		onSaveForce: () => void;
		onBack: () => void;
		toolFuncMap?: Record<string, string[]>;
	} = $props();

	let cognitionOpen = $state(false);
	let validating = $state(false);
	let validateTimer: ReturnType<typeof setTimeout> | null = $state(null);

	const hasErrors = $derived(issues.some((i) => i.severity === 'error'));

	function handleYamlInput() {
		if (validateTimer) clearTimeout(validateTimer);
		validateTimer = setTimeout(async () => {
			if (!yamlText.trim()) {
				issues = [];
				return;
			}
			validating = true;
			try {
				const result = await validateYaml(yamlText);
				issues = result.issues;
			} catch {
				// skip
			} finally {
				validating = false;
			}
		}, 500);
	}

	onDestroy(() => {
		if (validateTimer) clearTimeout(validateTimer);
	});
</script>

{#if explanation}
	<div class="border-l-2 border-l-info bg-info/5 px-3 py-2">
		<p class="text-[13px] text-fg-muted">{explanation}</p>
	</div>
{/if}

<!-- Toolbar -->
<div class="flex items-center justify-end">
	<button
		class="flex items-center gap-1.5 px-3 py-1.5 font-mono text-[12px] transition-[color,background-color,border-color] duration-150 border
			{cognitionOpen
				? 'border-accent-primary/30 bg-accent-primary/10 text-accent-primary'
				: 'border-accent-primary/20 bg-accent-primary/[0.06] text-accent-primary/70 hover:bg-accent-primary/10 hover:text-accent-primary'}"
		onclick={() => (cognitionOpen = !cognitionOpen)}
		aria-pressed={cognitionOpen}
	>
		<Brain size={13} strokeWidth={1.5} />
		Cognition
	</button>
</div>

<!-- Editor + Cognition panel -->
<div class="flex gap-4">
	<!-- YAML editor column -->
	<div class="min-w-0 flex-1 space-y-0">
		<textarea
			bind:value={yamlText}
			oninput={handleYamlInput}
			class="w-full resize-y border border-edge bg-surface-0 p-4 font-mono text-[13px] leading-relaxed text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			style="min-height: 400px"
			spellcheck="false"
			aria-label="Role YAML editor"
		></textarea>

		{#if issues.length > 0}
			<div class="space-y-1" role="alert">
				{#each issues as issue}
					<div
						class="flex items-start gap-2 px-3 py-1.5 {issue.severity === 'error' ? 'bg-fail/5' : issue.severity === 'warning' ? 'bg-warn/5' : ''}"
					>
						{#if issue.severity === 'error'}
							<CircleX size={13} class="mt-0.5 shrink-0 text-fail" />
						{:else if issue.severity === 'warning'}
							<TriangleAlert size={13} class="mt-0.5 shrink-0 text-warn" />
						{:else}
							<Info size={13} class="mt-0.5 shrink-0 text-fg-faint" />
						{/if}
						<span class="font-mono text-[13px]" class:text-fail={issue.severity === 'error'} class:text-warn={issue.severity === 'warning'} class:text-fg-faint={issue.severity === 'info'}>
							{issue.field}: {issue.message}
						</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>

	<!-- Cognition panel column -->
	{#if cognitionOpen}
		<div class="w-72 shrink-0 border border-edge bg-surface-0 p-4">
			<CognitionPanel
				{yamlText}
				onUpdate={(newYaml) => {
					yamlText = newYaml;
					handleYamlInput();
				}}
				{toolFuncMap}
			/>
		</div>
	{/if}
</div>

<div>
	<h2 class="mb-3 font-mono text-[12px] font-medium uppercase tracking-[0.1em] text-fg-faint">
		Save to
	</h2>
	<div class="flex items-center gap-2">
		<select
			class="border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none"
			bind:value={selectedDir}
		>
			{#each roleDirs as dir}
				<option value={dir}>{dir}</option>
			{/each}
		</select>
		<span class="text-fg-faint">/</span>
		<input
			type="text"
			bind:value={filename}
			class="min-w-0 flex-1 border border-edge bg-surface-1 px-3 py-2 font-mono text-[13px] text-fg outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			placeholder="role.yaml"
		/>
	</div>
</div>

{#if showOverwrite}
	<div class="flex items-center gap-3 border-l-2 border-l-warn bg-warn/5 px-3 py-2">
		<TriangleAlert size={14} class="shrink-0 text-warn" />
		<span class="flex-1 text-[13px] text-fg-muted">File already exists at {selectedDir}/{filename}</span>
		<button
			class="bg-warn/20 px-3 py-1 text-[13px] font-medium text-warn transition-[background-color] duration-150 hover:bg-warn/30"
			onclick={onSaveForce}
		>
			Overwrite
		</button>
	</div>
{/if}

{#if saveError}
	<div class="border-l-2 border-l-fail bg-fail/5 px-3 py-2">
		<p class="text-[13px] text-fail">{saveError}</p>
	</div>
{/if}

<div class="flex gap-3">
	<button
		class="rounded-full border border-edge bg-surface-1 px-5 py-2 text-[13px] font-medium text-fg-muted transition-[color,background-color,border-color] duration-150 hover:bg-surface-2 hover:text-fg hover:border-accent-primary/20"
		onclick={onBack}
	>
		Back
	</button>
	<button
		class="flex items-center gap-2 rounded-full bg-accent-primary px-6 py-2.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)] disabled:opacity-40"
		disabled={hasErrors || saving || !yamlText.trim() || !filename.trim()}
		onclick={onSave}
	>
		{#if saving}
			<Loader2 size={14} class="animate-spin" />
			Saving...
		{:else}
			Save Agent
		{/if}
	</button>
</div>
