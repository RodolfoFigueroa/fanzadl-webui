<script lang="ts">
import { onMount } from 'svelte';
import { goto } from '$app/navigation';
import { getSettings, login } from '$lib/api';

let email = $state('');
let password = $state('');
let error = $state<string | null>(null);
let loading = $state(false);

onMount(async () => {
    try {
        await getSettings();
        goto('/');
    } catch {
        // not authenticated — stay on login page
    }
});

async function handleSubmit(e: Event) {
    e.preventDefault();
    error = null;
    loading = true;
    try {
        await login(email, password);
        goto('/');
    } catch (err) {
        error = err instanceof Error ? err.message : 'Login failed';
    } finally {
        loading = false;
    }
}
</script>

<svelte:head>
    <title>Sign in — FanzaDL</title>
</svelte:head>

<div class="flex-1 flex items-center justify-center">
    <div
        class="bg-th-surface border border-th-border rounded-xl p-8 w-full max-w-sm shadow-md"
    >
        <h1 class="text-th-brand font-bold text-xl mb-6 tracking-tight">
            FanzaDL
        </h1>
        <form onsubmit={handleSubmit} class="flex flex-col gap-4">
            <div class="flex flex-col gap-1">
                <label
                    for="email"
                    class="text-sm font-medium text-th-text-muted">Email</label
                >
                <input
                    id="email"
                    type="email"
                    bind:value={email}
                    required
                    autocomplete="email"
                    class="bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-sm text-th-text
                        focus:outline-none focus:ring-2 focus:ring-th-border-strong focus:border-transparent
                        transition-shadow"
                />
            </div>
            <div class="flex flex-col gap-1">
                <label
                    for="password"
                    class="text-sm font-medium text-th-text-muted"
                    >Password</label
                >
                <input
                    id="password"
                    type="password"
                    bind:value={password}
                    required
                    autocomplete="current-password"
                    class="bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-sm text-th-text
                        focus:outline-none focus:ring-2 focus:ring-th-border-strong focus:border-transparent
                        transition-shadow"
                />
            </div>
            {#if error}
                <p class="text-sm text-red-500">{error}</p>
            {/if}
            <button
                type="submit"
                disabled={loading}
                class="bg-th-accent text-th-accent-text rounded-lg px-4 py-2 text-sm font-medium
                    hover:bg-th-accent-hover transition-colors disabled:opacity-50"
            >
                {loading ? "Signing in…" : "Sign in"}
            </button>
        </form>
    </div>
</div>
