<script lang="ts">
	import { useSvelteFlow, useNodesInitialized } from '@xyflow/svelte';

	const { fitView } = useSvelteFlow();
	const nodesInitialized = useNodesInitialized();

	let hasFit = $state(false);

	$effect(() => {
		if (nodesInitialized.current && !hasFit) {
			hasFit = true;
			fitView({ padding: 0.15, duration: 300 });
		}
	});
</script>
