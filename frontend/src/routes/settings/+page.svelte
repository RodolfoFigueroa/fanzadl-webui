<script lang="ts">
import { onMount } from 'svelte';
import { goto } from '$app/navigation';
import {
    getCachedSettings,
    getSettings,
    logout,
    updateSettings,
} from '$lib/api';

async function handleLogout() {
    try {
        await logout();
    } finally {
        goto('/login');
    }
}

let threadCount = $state(getCachedSettings()?.download_thread_count ?? 4);
let maxConcurrentDownloads = $state(
    getCachedSettings()?.max_concurrent_downloads ?? 3,
);
let logLevel = $state(getCachedSettings()?.log_level ?? 'INFO');
let javstashEnabled = $state(getCachedSettings()?.javstash_enabled ?? false);

let javstashKeyInput = $state('');
let javstashSaving = $state(false);
let javstashError = $state('');

onMount(async () => {
    const s = await getSettings();
    threadCount = s.download_thread_count;
    maxConcurrentDownloads = s.max_concurrent_downloads;
    logLevel = s.log_level;
    javstashEnabled = s.javstash_enabled;
});

async function handleSaveJavstashKey() {
    if (!javstashKeyInput.trim()) return;
    javstashSaving = true;
    javstashError = '';
    try {
        const s = await updateSettings({
            javstash_api_key: javstashKeyInput.trim(),
        });
        javstashEnabled = s.javstash_enabled;
        javstashKeyInput = '';
    } catch (e) {
        javstashError =
            e instanceof Error ? e.message : 'Failed to save API key';
    } finally {
        javstashSaving = false;
    }
}

async function handleClearJavstashKey() {
    javstashSaving = true;
    javstashError = '';
    try {
        const s = await updateSettings({ javstash_api_key: null });
        javstashEnabled = s.javstash_enabled;
    } catch (e) {
        javstashError =
            e instanceof Error ? e.message : 'Failed to clear API key';
    } finally {
        javstashSaving = false;
    }
}
</script>

<svelte:head>
    <title>Settings — FanzaDL</title>
</svelte:head>

<div class="max-w-md mx-auto mt-6 sm:mt-16">
    <h1 class="text-2xl font-bold mb-6">Settings</h1>
    <div
        class="bg-th-surface rounded-xl p-6 border border-th-border space-y-4 mt-4"
    >
        <div>
            <label
                class="block text-sm font-medium text-th-text-muted mb-1.5"
                for="thread-count"
            >
                Download thread count
            </label>
            <p class="text-xs text-th-text-dim mb-2">
                Number of parallel threads used by N_m3u8DL-RE (1-32). Each
                simultaneous download uses this amount of threads.
            </p>
            <input
                id="thread-count"
                type="number"
                min="1"
                max="32"
                bind:value={threadCount}
                onchange={() => {
                    threadCount = Math.min(32, Math.max(1, threadCount));
                    updateSettings({ download_thread_count: threadCount });
                }}
                class="w-24 bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-th-text
					focus:outline-none focus:ring-2 focus:ring-th-border-strong focus:border-transparent
					transition-shadow"
            />
        </div>
        <div>
            <label
                class="block text-sm font-medium text-th-text-muted mb-1.5"
                for="max-concurrent-downloads"
            >
                Maximum simultaneous downloads
            </label>
            <p class="text-xs text-th-text-dim mb-2">
                How many downloads may run at the same time. Additional
                downloads are queued and start automatically.
            </p>
            <input
                id="max-concurrent-downloads"
                type="number"
                min="1"
                bind:value={maxConcurrentDownloads}
                onchange={() => {
                    maxConcurrentDownloads = Math.max(
                        1,
                        maxConcurrentDownloads,
                    );
                    updateSettings({
                        max_concurrent_downloads: maxConcurrentDownloads,
                    });
                }}
                class="w-24 bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-th-text
					focus:outline-none focus:ring-2 focus:ring-th-border-strong focus:border-transparent
					transition-shadow"
            />
        </div>
        <div>
            <label
                class="block text-sm font-medium text-th-text-muted mb-1.5"
                for="log-level"
            >
                Log level
            </label>
            <p class="text-xs text-th-text-dim mb-2">
                Controls the verbosity of server-side logging. DEBUG produces
                the most output; ERROR only logs failures.
            </p>
            <select
                id="log-level"
                bind:value={logLevel}
                onchange={() => updateSettings({ log_level: logLevel })}
                class="w-32 bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-th-text
					focus:outline-none focus:ring-2 focus:ring-th-border-strong focus:border-transparent
					transition-shadow"
            >
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
            </select>
        </div>
        <div>
            <label
                class="block text-sm font-medium text-th-text-muted mb-1.5"
                for="javstash-api-key"
            >
                JAVstash API key
            </label>
            <p class="text-xs text-th-text-dim mb-2">
                API key for Javstash metadata lookups. Leave blank to keep the
                current key. The key is stored encrypted on the server.
            </p>
            <div class="flex items-center gap-2 mb-1">
                <span class="text-xs {javstashEnabled ? 'text-green-400' : 'text-th-text-dim'}">
                    {javstashEnabled ? 'Configured' : 'Not set'}
                </span>
            </div>
            <div class="flex gap-2">
                <input
                    id="javstash-api-key"
                    type="password"
                    placeholder="Enter new API key"
                    bind:value={javstashKeyInput}
                    disabled={javstashSaving}
                    class="flex-1 bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-th-text
                        focus:outline-none focus:ring-2 focus:ring-th-border-strong focus:border-transparent
                        transition-shadow disabled:opacity-50"
                />
                <button
                    onclick={handleSaveJavstashKey}
                    disabled={javstashSaving || !javstashKeyInput.trim()}
                    class="px-3 py-2 text-sm rounded-lg border border-th-border hover:border-th-border-strong
                        text-th-text-muted hover:text-th-text transition-colors disabled:opacity-40"
                >
                    Save
                </button>
                {#if javstashEnabled}
                    <button
                        onclick={handleClearJavstashKey}
                        disabled={javstashSaving}
                        class="px-3 py-2 text-sm rounded-lg border border-th-border hover:border-red-800
                            text-th-text-dim hover:text-red-400 transition-colors disabled:opacity-40"
                    >
                        Clear
                    </button>
                {/if}
            </div>
            {#if javstashError}
                <p class="text-xs text-red-400 mt-1">{javstashError}</p>
            {/if}
        </div>
    </div>

    <button
        onclick={handleLogout}
        class="sm:hidden mt-4 w-full text-sm text-th-text-dim hover:text-red-400 border border-th-border
            hover:border-red-800 rounded-xl py-3 transition-colors"
    >
        Logout
    </button>
</div>
