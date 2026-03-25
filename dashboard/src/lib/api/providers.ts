import { request } from './client';
import type { ProviderStatus } from './builder';

export interface ProviderStatusResponse {
	providers: ProviderStatus[];
	detected_provider: string | null;
	detected_model: string | null;
}

export interface SaveKeyResult {
	env_var: string;
	validated: boolean;
	validation_supported: boolean;
}

export function getProviderStatus(): Promise<ProviderStatusResponse> {
	return request('/api/providers/status');
}

export function saveProviderKey(body: {
	provider?: string;
	preset?: string;
	base_url?: string;
	api_key: string;
	verify?: boolean;
}): Promise<SaveKeyResult> {
	return request('/api/providers/save-key', {
		method: 'POST',
		body: JSON.stringify(body)
	});
}
