<script lang="ts">
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { onMount } from 'svelte';
	import { getSkillDetail, getSkillContent, deleteSkill } from '$lib/api/skills';
	import type { SkillDetail } from '$lib/api/types';
	import { loadOr404 } from '$lib/utils/load';
	import { toast } from '$lib/stores/toast.svelte';
	import { Skeleton } from '$lib/components/ui/skeleton';
	import { Tabs, TabsContent, TabsList, TabsTrigger } from '$lib/components/ui/tabs';
	import ConfirmDeleteDialog from '$lib/components/ui/ConfirmDeleteDialog.svelte';
	import LoadError from '$lib/components/ui/LoadError.svelte';
	import ScopeBadge from '$lib/components/skills/ScopeBadge.svelte';
	import SkillConfigPanel from '$lib/components/skills/SkillConfigPanel.svelte';
	import SkillEditorTab from '$lib/components/skills/SkillEditorTab.svelte';
	import { ArrowLeft, Settings, FileCode, Trash2 } from 'lucide-svelte';

	let detail: SkillDetail | null = $state(null);
	let content = $state('');
	let skillPath = $state('');
	let loading = $state(true);
	let loadError = $state(false);
	let deleteDialogOpen = $state(false);

	const skillId = $derived(page.params.id ?? '');

	const tabKey = $derived(`skill-tab-${skillId}`);
	let activeTab = $state('overview');

	function onTabChange(value: string) {
		activeTab = value;
		try {
			localStorage.setItem(tabKey, value);
		} catch {
			// ignore
		}
	}

	async function reload() {
		const [d, c] = await Promise.all([getSkillDetail(skillId), getSkillContent(skillId)]);
		detail = d;
		content = c.content;
		skillPath = c.path;
	}

	onMount(async () => {
		// Restore saved tab
		try {
			const saved = localStorage.getItem(tabKey);
			if (saved && ['overview', 'editor'].includes(saved)) {
				activeTab = saved;
			}
		} catch {
			// ignore
		}

		const result = await loadOr404(() => reload(), 'Failed to load skill');
		if (!result.ok && !result.notFound) loadError = true;
		loading = false;
	});

	async function handleDelete() {
		try {
			await deleteSkill(skillId);
			goto('/skills');
		} catch (err: unknown) {
			// Check for blocked delete (409 with resource files)
			if (err && typeof err === 'object' && 'status' in err && (err as { status: number }).status === 409) {
				toast.error('Cannot delete: skill directory contains resource files. Remove them manually.');
			} else {
				toast.error('Failed to delete skill');
			}
		}
	}
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

	{#if loading}
		<Skeleton class="h-6 w-48 bg-surface-1" />
		<Skeleton class="h-10 bg-surface-1" />
		<Skeleton class="h-64 bg-surface-1" />
	{:else if loadError}
		<LoadError message="Failed to load skill" onRetry={() => location.reload()} />
	{:else if detail}
		<!-- Header -->
		<div>
			<div class="flex items-center gap-3">
				<h1
					class="text-xl font-semibold tracking-[-0.02em] text-fg"
					style="text-wrap: balance"
				>
					{detail.name}
				</h1>
				<ScopeBadge scope={detail.scope} />
				{#if detail.requirements.length > 0}
					<span
						class="inline-block h-2 w-2 rounded-full {detail.requirements_met
							? 'bg-ok'
							: 'bg-warn'}"
						style="box-shadow: 0 0 6px var({detail.requirements_met
							? '--color-ok'
							: '--color-warn'})"
					></span>
				{/if}
				<button
					class="ml-auto flex items-center gap-1 rounded-[min(var(--radius-md),12px)] border border-transparent bg-destructive/10 px-2.5 py-1 text-[0.8rem] font-medium text-destructive transition-all hover:bg-destructive/20"
					onclick={() => (deleteDialogOpen = true)}
				>
					<Trash2 size={13} />
					Delete
				</button>
			</div>
			{#if detail.description}
				<p class="mt-1 text-[13px] text-fg-muted">{detail.description}</p>
			{/if}
		</div>

		<!-- Error block -->
		{#if detail.error}
			<div class="border-l-2 border-l-fail bg-fail/5 px-3 py-2">
				<p class="font-mono text-sm text-fail">{detail.error}</p>
			</div>
		{/if}

		<!-- Tabs -->
		<Tabs
			value={activeTab}
			onValueChange={onTabChange}
			class="flex min-h-0 flex-1 flex-col"
		>
			<TabsList
				variant="line"
				class="w-full justify-start gap-0 border-b border-edge bg-transparent px-0"
			>
				<TabsTrigger
					value="overview"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<Settings size={13} />
					Overview
				</TabsTrigger>
				<TabsTrigger
					value="editor"
					class="gap-1.5 rounded-none bg-transparent px-4 py-2 font-mono text-[13px] text-fg-faint transition-[color] duration-150 hover:text-fg-muted data-active:bg-transparent data-active:text-fg data-active:after:bg-accent-primary dark:data-active:bg-transparent dark:data-active:border-transparent"
				>
					<FileCode size={13} />
					Editor
				</TabsTrigger>
			</TabsList>

			<TabsContent value="overview" class="min-h-0 flex-1 pt-4">
				<div class="max-w-2xl">
					<SkillConfigPanel {detail} />
				</div>
			</TabsContent>

			<TabsContent value="editor" class="min-h-0 flex-1 pt-4">
				<SkillEditorTab
					{skillId}
					{content}
					path={skillPath}
					skillName={detail.name}
					onSaved={async () => {
						await reload();
					}}
				/>
			</TabsContent>
		</Tabs>

		<ConfirmDeleteDialog
			entityName={detail.name}
			entityType="skill"
			bind:open={deleteDialogOpen}
			onConfirm={handleDelete}
			onCancel={() => (deleteDialogOpen = false)}
		/>
	{:else}
		<p class="text-fg-faint">Skill not found</p>
	{/if}
</div>
