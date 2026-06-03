import { redirect } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';

// Disables SSR globally — this is a pure client-side SPA.
export const ssr = false;

export const load: LayoutLoad = async ({ url, fetch }) => {
    const res = await fetch('/api/settings/', { cache: 'no-store' });
    const authenticated = res.status !== 401;

    if (!authenticated && url.pathname !== '/login') {
        redirect(302, '/login');
    }
    if (authenticated && url.pathname === '/login') {
        redirect(302, '/');
    }

    const settingsJson = authenticated
        ? ((await res.json()) as {
              auth_disabled: boolean;
              fanza_connected: boolean;
          })
        : null;

    const authDisabled: boolean = settingsJson?.auth_disabled ?? false;
    const fanzaConnected: boolean = settingsJson?.fanza_connected ?? false;

    return { authenticated, authDisabled, fanzaConnected };
};
