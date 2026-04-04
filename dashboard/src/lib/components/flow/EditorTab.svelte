<script lang="ts">
	import { validateFlow, saveFlowYaml } from '$lib/api/flow';
	import YamlEditor from '$lib/components/ui/YamlEditor.svelte';

	let {
		flowId,
		yaml,
		path,
		flowName,
		onSaved
	}: {
		flowId: string;
		yaml: string;
		path: string;
		flowName: string;
		onSaved?: () => void;
	} = $props();

	async function validate(text: string) {
		return validateFlow(text);
	}

	async function save(text: string) {
		await saveFlowYaml(flowId, text);
	}
</script>

<YamlEditor
	{yaml}
	{path}
	entityName={flowName}
	nameChangeWarning="Changing the flow name will split event history. Existing events will remain under the previous name."
	{validate}
	{save}
	{onSaved}
/>
