<script lang="ts">
	import { Plus, ArrowDown } from 'lucide-svelte';
	import PersonaCard from './PersonaCard.svelte';
	import type { ProviderModels, ProviderPreset } from '$lib/api/types';

	const DEFAULT_NAMES = [
		'analyst',
		'reviewer',
		'advisor',
		'checker',
		'specialist',
		'evaluator',
		'auditor',
		'planner'
	];

	const NAME_RE = /^[a-z0-9][a-z0-9-]*[a-z0-9]$/;

	export interface PersonaEntry {
		name: string;
		role: string;
		modelOverride: boolean;
		modelProvider: string;
		modelName: string;
		modelCustomName: string;
		modelBaseUrl: string;
		modelApiKey: string;
	}

	let {
		personas = $bindable(),
		strategy,
		providers,
		customPresets,
		ollamaModels,
		ollamaBaseUrl
	}: {
		personas: PersonaEntry[];
		strategy: 'sequential' | 'parallel';
		providers: ProviderModels[];
		customPresets: ProviderPreset[];
		ollamaModels: string[];
		ollamaBaseUrl: string;
	} = $props();

	// -- Validation ---------------------------------------------------------------

	function nameError(index: number): string | null {
		const name = personas[index].name;
		if (!name) return 'Name required';
		if (!NAME_RE.test(name)) return 'Lowercase letters, digits, and hyphens only';
		const dup = personas.findIndex((p, i) => i !== index && p.name === name);
		if (dup !== -1) return 'Duplicate name';
		return null;
	}

	// -- Actions ------------------------------------------------------------------

	function updateField(index: number, field: string, value: any) {
		const updated = [...personas];
		(updated[index] as any)[field] = value;
		personas = updated;
	}

	function addPersona() {
		if (personas.length >= 8) return;
		const usedNames = new Set(personas.map((p) => p.name));
		const nextName = DEFAULT_NAMES.find((n) => !usedNames.has(n)) ?? `persona-${personas.length + 1}`;
		personas = [
			...personas,
			{
				name: nextName,
				role: '',
				modelOverride: false,
				modelProvider: providers[0]?.provider ?? '',
				modelName: providers[0]?.models[0]?.name ?? '',
				modelCustomName: '',
				modelBaseUrl: '',
				modelApiKey: ''
			}
		];
	}

	function removePersona(index: number) {
		if (personas.length <= 2) return;
		personas = personas.filter((_, i) => i !== index);
	}

	function moveUp(index: number) {
		if (index <= 0) return;
		const updated = [...personas];
		[updated[index - 1], updated[index]] = [updated[index], updated[index - 1]];
		personas = updated;
	}

	function moveDown(index: number) {
		if (index >= personas.length - 1) return;
		const updated = [...personas];
		[updated[index], updated[index + 1]] = [updated[index + 1], updated[index]];
		personas = updated;
	}
</script>

<div class="space-y-0">
	{#each personas as persona, idx (persona.name + '-' + idx)}
		<!-- Arrow connector for sequential -->
		{#if idx > 0 && strategy === 'sequential'}
			<div class="flex justify-center py-1">
				<ArrowDown size={14} class="text-accent-primary/60" />
			</div>
		{:else if idx > 0}
			<div class="h-2"></div>
		{/if}

		<PersonaCard
			index={idx}
			name={persona.name}
			role={persona.role}
			modelOverride={persona.modelOverride}
			bind:modelProvider={persona.modelProvider}
			bind:modelName={persona.modelName}
			bind:modelCustomName={persona.modelCustomName}
			bind:modelBaseUrl={persona.modelBaseUrl}
			bind:modelApiKey={persona.modelApiKey}
			{strategy}
			canRemove={personas.length > 2}
			canMoveUp={idx > 0}
			canMoveDown={idx < personas.length - 1}
			{providers}
			{customPresets}
			{ollamaModels}
			{ollamaBaseUrl}
			nameError={nameError(idx)}
			onUpdate={(field, value) => updateField(idx, field, value)}
			onRemove={() => removePersona(idx)}
			onMoveUp={() => moveUp(idx)}
			onMoveDown={() => moveDown(idx)}
		/>
	{/each}

	<!-- Add persona button -->
	{#if personas.length < 8}
		<div class="flex justify-center pt-3">
			<button
				class="flex items-center gap-1.5 rounded-full border border-edge bg-surface-1 px-3 py-1.5 font-mono text-[12px] text-fg-faint transition-[color,background-color,border-color] duration-150 hover:border-accent-primary/30 hover:bg-surface-2 hover:text-fg-muted"
				onclick={addPersona}
			>
				<Plus size={12} />
				Add persona
			</button>
		</div>
	{/if}
</div>
