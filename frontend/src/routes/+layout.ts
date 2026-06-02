import { redirect } from '@sveltejs/kit';
import type { LayoutLoad } from './$types';

// Disables SSR globally — this is a pure client-side SPA.
export const ssr = false;

export const load: LayoutLoad = async ({ url, fetch }) => {
    if (url.pathname === '/login') return {};
    const res = await fetch('/api/settings');
    if (res.status === 401) {
        redirect(302, '/login');
    }
    return {};
};
