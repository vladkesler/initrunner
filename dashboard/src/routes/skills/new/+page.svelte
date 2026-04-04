<script lang="ts">
	import { goto } from '$app/navigation';
	import { onMount } from 'svelte';
	import { createSkill, getSkillDirectories } from '$lib/api/skills';
	import { toast } from '$lib/stores/toast.svelte';
	import { ArrowLeft, AlertCircle } from 'lucide-svelte';
	import { setCrumbs } from '$lib/stores/breadcrumb.svelte';

	$effect(() => { setCrumbs([{ label: 'Skills', href: '/skills' }, { label: 'New Skill' }]); });

	let name = $state('');
	let directory = $state('');
	let directories = $state<string[]>([]);
	let provider = $state('openai');
	let saving = $state(false);
	let nameError = $state('');

	const namePattern = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/;
	const canSave = $derived(name.length >= 2 && !nameError && directory && !saving);

	function validateName() {
		if (!name) {
			nameError = '';
			return;
		}
		if (name.length < 2) {
			nameError = 'Name must be at least 2 characters';
			return;
		}
		if (!namePattern.test(name)) {
			nameError = 'Must be lowercase alphanumeric with hyphens (e.g. my-skill)';
			return;
		}
		nameError = '';
	}

	async function handleCreate() {
		saving = true;
		try {
			const result = await createSkill({ name, directory, provider });
			goto(`/skills/${result.id}`);
		} catch (err) {
			toast.error(err instanceof Error ? err.message : 'Failed to create skill');
		} finally {
			saving = false;
		}
	}

	onMount(async () => {
		try {
			directories = await getSkillDirectories();
			if (directories.length > 0) {
				directory = directories[0];
			}
		} catch {
			toast.error('Failed to load directories');
		}
	});
</script>

<div class="flex h-full flex-col gap-5">
	<!-- Back link -->
	<a
		href="/skills"
		class="inline-flex items-center gap-1.5 text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted"
	>
		<ArrowLeft size={14} />
		Skills
	</a>

	<h1 class="text-2xl font-semibold tracking-[-0.03em] text-fg">New Skill</h1>

	<div class="max-w-md space-y-5">
		<!-- Name -->
		<div class="space-y-1.5">
			<label
				for="skill-name"
				class="section-label"
			>
				Name
			</label>
			<input
				id="skill-name"
				type="text"
				bind:value={name}
				onblur={validateName}
				oninput={validateName}
				placeholder="my-skill"
				class="w-full border border-edge bg-surface-0 px-3 py-2 font-mono text-[13px] text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			/>
			{#if nameError}
				<div class="flex items-center gap-1.5 text-[13px] text-fail">
					<AlertCircle size={13} />
					{nameError}
				</div>
			{/if}
		</div>

		<!-- Directory -->
		<div class="space-y-1.5">
			<label
				for="skill-dir"
				class="section-label"
			>
				Directory
			</label>
			<select
				id="skill-dir"
				bind:value={directory}
				class="w-full border border-edge bg-surface-0 px-3 py-2 font-mono text-[13px] text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			>
				{#each directories as dir}
					<option value={dir}>{dir}</option>
				{/each}
			</select>
		</div>

		<!-- Provider -->
		<div class="space-y-1.5">
			<label
				for="skill-provider"
				class="section-label"
			>
				Provider (for template defaults)
			</label>
			<select
				id="skill-provider"
				bind:value={provider}
				class="w-full border border-edge bg-surface-0 px-3 py-2 font-mono text-[13px] text-fg-muted outline-none transition-[border-color,box-shadow] duration-150 focus:border-accent-primary/40 focus:shadow-[0_0_0_3px_oklch(0.91_0.20_128/0.08)]"
			>
				<option value="openai">openai</option>
				<option value="anthropic">anthropic</option>
				<option value="ollama">ollama</option>
			</select>
		</div>

		<!-- Create button -->
		<button
			class="inline-flex items-center gap-1.5 rounded-[2px] bg-accent-primary px-5 py-2 text-[13px] font-medium text-surface-0 transition-[background-color,box-shadow] duration-150 hover:bg-accent-primary-hover disabled:opacity-40"
			onclick={handleCreate}
			disabled={!canSave}
		>
			{saving ? 'Creating...' : 'Create Skill'}
		</button>
	</div>
</div>
