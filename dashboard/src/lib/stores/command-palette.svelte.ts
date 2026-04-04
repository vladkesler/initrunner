let open = $state(false);

export function isPaletteOpen(): boolean {
	return open;
}

export function togglePalette(): void {
	open = !open;
}

export function openPalette(): void {
	open = true;
}

export function closePalette(): void {
	open = false;
}
