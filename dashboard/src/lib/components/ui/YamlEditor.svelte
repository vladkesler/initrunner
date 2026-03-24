<script lang="ts">
	import { onMount } from 'svelte';
	import { Copy, Check, AlertCircle, AlertTriangle, Save, RotateCcw } from 'lucide-svelte';

	export type ValidationIssue = { field: string; message: string; severity: string };

	let {
		yaml,
		path,
		entityName,
		nameChangeWarning,
		validate,
		save,
		onSaved
	}: {
		yaml: string;
		path: string;
		entityName: string;
		nameChangeWarning: string;
		validate: (text: string) => Promise<{ issues: ValidationIssue[] }>;
		save: (text: string) => Promise<void>;
		onSaved?: () => void;
	} = $props();

	let yamlText = $state('');
	let issues = $state<ValidationIssue[]>([]);
	let validating = $state(false);
	let saving = $state(false);
	let saveSuccess = $state(false);
	let saveError = $state<string | null>(null);
	let copied = $state(false);
	let nameWarning = $state(false);
	let validateTimer: ReturnType<typeof setTimeout> | null = null;

	const hasChanges = $derived(yamlText !== yaml);
	const hasErrors = $derived(issues.some((i) => i.severity === 'error'));
	const canSave = $derived(hasChanges && !hasErrors && !saving && !validating);

	const filename = $derived(path.substring(path.lastIndexOf('/') + 1));

	onMount(() => {
		yamlText = yaml;
	});

	function onInput() {
		saveSuccess = false;
		saveError = null;
		if (validateTimer) clearTimeout(validateTimer);
		validateTimer = setTimeout(runValidation, 800);
	}

	async function runValidation() {
		if (!yamlText.trim()) {
			issues = [];
			nameWarning = false;
			return;
		}
		validating = true;
		try {
			const result = await validate(yamlText);
			issues = result.issues;
			// Check for name change
			const match = yamlText.match(/^\s*name:\s*(.+)$/m);
			const parsedName = match?.[1]?.trim();
			nameWarning = !!parsedName && parsedName !== entityName;
		} catch {
			// validation API unavailable
		} finally {
			validating = false;
		}
	}

	async function handleSave() {
		saving = true;
		saveError = null;
		saveSuccess = false;
		try {
			await save(yamlText);
			saveSuccess = true;
			onSaved?.();
		} catch (err) {
			saveError = err instanceof Error ? err.message : 'Save failed';
		} finally {
			saving = false;
		}
	}

	function handleReset() {
		yamlText = yaml;
		issues = [];
		nameWarning = false;
		saveSuccess = false;
		saveError = null;
	}

	async function copyYaml() {
		await navigator.clipboard.writeText(yamlText);
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}
</script>

<div class="space-y-3">
	<!-- Toolbar -->
	<div class="flex items-center gap-2">
		<button
			class="inline-flex items-center gap-1.5 rounded-full bg-accent-primary px-4 py-1.5 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover hover:shadow-[0_0_16px_oklch(0.91_0.20_128/0.25)] disabled:opacity-40"
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
			onclick={copyYaml}
			aria-label="Copy YAML"
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

		{#if validating}
			<span class="text-[12px] text-fg-faint">Validating...</span>
		{/if}
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
				{nameChangeWarning}
			</p>
		</div>
	{/if}

	<!-- Editor -->
	<textarea
		bind:value={yamlText}
		oninput={onInput}
		class="min-h-[500px] w-full resize-y border border-edge bg-surface-0 p-4 font-mono text-[13px] leading-relaxed text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
		spellcheck="false"
	></textarea>

	<!-- Validation issues -->
	{#if issues.length > 0}
		<div class="space-y-1">
			{#each issues as issue}
				<div class="flex items-start gap-2 font-mono text-[13px]">
					{#if issue.severity === 'error'}
						<AlertCircle size={14} class="mt-0.5 shrink-0 text-fail" />
					{:else}
						<AlertTriangle size={14} class="mt-0.5 shrink-0 text-warn" />
					{/if}
					<span class={issue.severity === 'error' ? 'text-fail' : 'text-warn'}>
						{issue.field}:
					</span>
					<span class="text-fg-muted">{issue.message}</span>
				</div>
			{/each}
		</div>
	{/if}
</div>
