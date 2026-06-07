/**
 * Anonymous, opt-in usage telemetry for the dashboard (posthog-js).
 *
 * Mirrors the CLI: no autocapture, no session recording, no heatmaps, no input
 * contents, and anonymous events (no person profiles). It stays inert until the
 * user accepts the consent banner (localStorage), and never starts when the
 * browser sets Do Not Track or no PostHog key is configured at build time. Every
 * entry point is best-effort.
 */
import posthog from 'posthog-js';

import { safeGet, safeSet } from '$lib/utils/storage';

const KEY = import.meta.env.VITE_POSTHOG_KEY ?? 'phc_xCsEKz7e2YnCzneVDsPd3moRDnK5PaHudUridGfAJCrw';
const HOST = import.meta.env.VITE_POSTHOG_HOST ?? 'https://us.i.posthog.com';

const CONSENT_KEY = 'telemetry-consent';
const LEGACY_OPT_OUT_KEY = 'telemetry-opt-out';

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

export function consentState(): 'unset' | 'granted' | 'denied' {
	const v = safeGet(CONSENT_KEY);
	if (v === 'granted' || v === 'denied') return v;
	// Migrate the legacy opt-out flag: an explicit opt-out becomes 'denied';
	// anything else is treated as undecided so the user is asked under opt-in.
	if (safeGet(LEGACY_OPT_OUT_KEY) === 'true') return 'denied';
	return 'unset';
}

/** Telemetry is possible only with a key configured and DNT off. */
export function telemetryAvailable(): boolean {
	return Boolean(KEY) && !doNotTrack();
}

/** Show the consent banner only when telemetry is possible and undecided. */
export function needsConsentPrompt(): boolean {
	return telemetryAvailable() && consentState() === 'unset';
}

export function initTelemetry(): void {
	if (started || !telemetryAvailable() || consentState() !== 'granted') return;
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
			capture_dead_clicks: false,
			// Override the source IP so PostHog never stores the real one.
			before_send: (event) => {
				if (event) event.properties = { ...event.properties, $ip: '0.0.0.0' };
				return event;
			}
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

export function setConsent(granted: boolean): void {
	safeSet(CONSENT_KEY, granted ? 'granted' : 'denied');
	try {
		if (granted) {
			if (!started) initTelemetry();
			posthog.opt_in_capturing();
		} else if (started) {
			posthog.opt_out_capturing();
		}
	} catch {
		/* best-effort */
	}
}
