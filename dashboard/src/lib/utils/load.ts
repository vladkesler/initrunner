import { ApiError } from '$lib/api/client';
import { toast } from '$lib/stores/toast.svelte';

export type LoadResult = { ok: true } | { ok: false; notFound: boolean };

/**
 * Attempt an async load, discriminating 404 (not found) from other failures.
 * Non-404 errors fire a toast. 404 errors are returned silently.
 */
export async function loadOr404(
	fn: () => Promise<unknown>,
	errorMessage: string
): Promise<LoadResult> {
	try {
		await fn();
		return { ok: true };
	} catch (e) {
		if (e instanceof ApiError && e.status === 404) {
			return { ok: false, notFound: true };
		}
		toast.error(errorMessage);
		return { ok: false, notFound: false };
	}
}
