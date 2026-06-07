/**
 * Anonymous, opt-out usage telemetry for the dashboard (posthog-js).
 *
 * Mirrors the CLI: no autocapture, no session recording, no heatmaps, no input
 * contents, and anonymous events (no person profiles). It stays inert when the
 * user opts out (localStorage), the browser sets Do Not Track, or no PostHog key
 * is configured at build time. Every entry point is best-effort.
 */
import posthog from 'posthog-js';

import { safeGet, safeSet } from '$lib/utils/storage';

const KEY = import.meta.env.VITE_POSTHOG_KEY ?? 'phc_xCsEKz7e2YnCzneVDsPd3moRDnK5PaHudUridGfAJCrw';
const HOST = import.meta.env.VITE_POSTHOG_HOST ?? 'https://us.i.posthog.com';

const OPT_OUT_KEY = 'telemetry-opt-out';
const NOTICE_KEY = 'telemetry-notice-dismissed';

let started = false;

function doNotTrack(): boolean {
	try {
		const dnt =
			navigator.doNotTrack ??
			// @ts-expect-error legacy vendor-prefixed flags
			window.doNotTrack ??
			// @ts-expect-error legacy vendor-prefixed flags
			navigator.msDoNotTrack;
		return dnt === '1' || dnt === 'yes' || dnt === true;
	} catch {
		return false;
	}
}

export function hasOptedOut(): boolean {
	return safeGet(OPT_OUT_KEY) === 'true';
}

/** Telemetry is possible only with a key configured and DNT off. */
export function telemetryAvailable(): boolean {
	return Boolean(KEY) && !doNotTrack();
}

export function initTelemetry(): void {
	if (started || !telemetryAvailable() || hasOptedOut()) return;
	try {
		posthog.init(KEY, {
			api_host: HOST,
			person_profiles: 'never',
			autocapture: false,
			capture_pageview: false,
			capture_pageleave: false,
			disable_session_recording: true,
			rageclick: false,
			enable_heatmaps: false,
			capture_dead_clicks: false
		});
		started = true;
	} catch {
		/* best-effort */
	}
}

export function capturePageview(path: string): void {
	if (!started) return;
	try {
		posthog.capture('$pageview', { $current_url: path });
	} catch {
		/* best-effort */
	}
}

export function captureEvent(event: string, props?: Record<string, unknown>): void {
	if (!started) return;
	try {
		posthog.capture(event, props);
	} catch {
		/* best-effort */
	}
}

export function setTelemetryEnabled(enabled: boolean): void {
	safeSet(OPT_OUT_KEY, enabled ? 'false' : 'true');
	try {
		if (enabled) {
			if (!started) initTelemetry();
			posthog.opt_in_capturing();
		} else if (started) {
			posthog.opt_out_capturing();
		}
	} catch {
		/* best-effort */
	}
}

export function noticeDismissed(): boolean {
	return safeGet(NOTICE_KEY) === 'true';
}

export function dismissNotice(): void {
	safeSet(NOTICE_KEY, 'true');
}
