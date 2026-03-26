export type ToastLevel = 'error' | 'success' | 'warn' | 'info';

export interface Toast {
	id: string;
	level: ToastLevel;
	message: string;
}

const MAX_TOASTS = 5;

let toasts = $state<Toast[]>([]);
let counter = 0;

function add(level: ToastLevel, message: string): void {
	const id = `toast-${++counter}`;
	if (toasts.length >= MAX_TOASTS) {
		toasts.shift();
	}
	toasts.push({ id, level, message });
	const delay = level === 'error' || level === 'warn' ? 8000 : 5000;
	setTimeout(() => dismissToast(id), delay);
}

export function dismissToast(id: string): void {
	toasts = toasts.filter((t) => t.id !== id);
}

export function getToasts(): Toast[] {
	return toasts;
}

export const toast = {
	error: (message: string) => add('error', message),
	success: (message: string) => add('success', message),
	warn: (message: string) => add('warn', message),
	info: (message: string) => add('info', message)
};
