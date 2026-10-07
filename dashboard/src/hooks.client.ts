import { initTelemetry } from '#lib/telemetry.ts';

/** Initialize anonymous, opt-in telemetry once on client boot (no-op until consented). */
export const init = () => {
	initTelemetry();
};
