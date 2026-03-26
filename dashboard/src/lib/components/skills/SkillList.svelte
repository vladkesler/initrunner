<script lang="ts">
	import type { SkillSummary } from '$lib/api/types';
	import SkillCard from './SkillCard.svelte';

	let { skills }: { skills: SkillSummary[] } = $props();
</script>

<div class="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
	{#each skills as skill, i}
		<div class="animate-fade-in-up" style="animation-delay: {Math.min(i * 60, 180)}ms">
			<SkillCard {skill} />
		</div>
	{/each}
</div>
