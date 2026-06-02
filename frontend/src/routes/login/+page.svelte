<script lang="ts">
import { goto } from '$app/navigation';
import { login } from '$lib/api';
import TextInput from '$lib/components/TextInput.svelte';

let password = $state('');
let error = $state<string | null>(null);
let loading = $state(false);

async function handleSubmit(e: Event) {
    e.preventDefault();
    error = null;
    loading = true;
    try {
        await login(password);
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
                    for="password"
                    class="text-sm font-medium text-th-text-muted"
                    >App Password</label
                >
                <TextInput
                    id="password"
                    type="password"
                    bind:value={password}
                    required
                    autocomplete="current-password"
                    class="text-sm"
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
