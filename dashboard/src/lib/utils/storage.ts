/** Safe localStorage wrappers for pywebview/WebKitGTK environments. */

export function safeGet(key: string): string | null {
	try {
		return localStorage.getItem(key);
	} catch {
		return null;
	}
}

export function safeSet(key: string, value: string): void {
	try {
		localStorage.setItem(key, value);
	} catch {
		/* best-effort -- storage unavailable in some WebView contexts */
	}
}
