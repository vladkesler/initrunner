import { request } from './client';

// -- Types --------------------------------------------------------------------

export interface TemplateInfo {
	name: string;
	description: string;
}

export interface ModelOption {
	name: string;
	description: string;
}

export interface ProviderModels {
	provider: string;
	models: ModelOption[];
}

export interface ProviderPreset {
	name: string;
	label: string;
	base_url: string;
	api_key_env: string;
	placeholder: string;
	key_configured: boolean;
}

export interface EnvVarStatus {
	name: string;
	is_set: boolean;
}

export interface TemplateSetup {
	steps: string[];
	env_vars: EnvVarStatus[];
	extras: string[];
	docs_url: string;
}

export interface ProviderStatus {
	provider: string;
	env_var: string;
	is_configured: boolean;
}

export interface BuilderOptions {
	templates: TemplateInfo[];
	providers: ProviderModels[];
	detected_provider: string | null;
	detected_model: string | null;
	role_dirs: string[];
	custom_presets: ProviderPreset[];
	ollama_models: string[];
	ollama_base_url: string;
	template_setups: Record<string, TemplateSetup>;
	provider_status: ProviderStatus[];
	tool_func_map: Record<string, string[]>;
}

export interface StarterInfo {
	slug: string;
	name: string;
	description: string;
	tags: string[];
	features: string[];
	kind: string;
}

export interface StartersResponse {
	starters: StarterInfo[];
}

export interface ValidationIssue {
	field: string;
	message: string;
	severity: 'error' | 'warning' | 'info';
}

export interface EmbeddingOption {
	provider: string;
	env_var: string;
	is_configured: boolean;
}

export interface EmbeddingWarning {
	llm_provider: string;
	feature: string;
	current_provider: string;
	options: EmbeddingOption[];
	message: string;
}

export interface SeedResult {
	yaml_text: string;
	explanation: string;
	issues: ValidationIssue[];
	ready: boolean;
	embedding_warning: EmbeddingWarning | null;
}

export interface SaveResult {
	path: string;
	valid: boolean;
	issues: string[];
	next_steps: string[];
	agent_id: string;
}

export interface HubSearchResult {
	owner: string;
	name: string;
	description: string;
	tags: string[];
	downloads: number;
	latest_version: string;
}

export interface HubSearchResponse {
	items: HubSearchResult[];
}

// -- API functions ------------------------------------------------------------

export function getBuilderOptions(): Promise<BuilderOptions> {
	return request('/api/builder/templates');
}

export function seedAgent(body: {
	mode: 'template' | 'description' | 'blank' | 'starter';
	name: string;
	template?: string;
	description?: string;
	starter_slug?: string;
	provider: string;
	model?: string;
	base_url?: string;
	api_key_env?: string;
}): Promise<SeedResult> {
	return request('/api/builder/seed', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function getStarters(): Promise<StartersResponse> {
	return request('/api/builder/starters');
}

export function validateYaml(yaml_text: string): Promise<SeedResult> {
	return request('/api/builder/validate', {
		method: 'POST',
		body: JSON.stringify({ yaml_text })
	});
}

export function setEmbeddingProvider(body: {
	yaml_text: string;
	embedding_provider: string;
}): Promise<SeedResult> {
	return request('/api/builder/set-embedding-provider', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function saveAgent(body: {
	yaml_text: string;
	directory: string;
	filename: string;
	force?: boolean;
}): Promise<SaveResult> {
	return request('/api/builder/save', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}

export function hubSearch(query: string, tags?: string[]): Promise<HubSearchResponse> {
	const params = new URLSearchParams({ q: query });
	if (tags) tags.forEach((t) => params.append('tag', t));
	return request(`/api/builder/hub-search?${params}`);
}

export function hubFeatured(): Promise<HubSearchResponse> {
	return request('/api/builder/hub-featured');
}

export function hubSeed(body: {
	ref: string;
	provider: string;
	model?: string;
	base_url?: string;
	api_key_env?: string;
}): Promise<SeedResult> {
	return request('/api/builder/hub-seed', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}
