<script lang="ts">
    import { onMount } from "svelte";
    import { goto } from "$app/navigation";
    import {
        getSettings,
        getThreadCount,
        setThreadCount,
        updateSettings,
        logout,
    } from "$lib/api";

    async function handleLogout() {
        try {
            await logout();
        } finally {
            goto("/login");
        }
    }

    let threadCount = $state(getThreadCount());
    let maxConcurrentDownloads = $state(3);

    onMount(async () => {
        const s = await getSettings();
        maxConcurrentDownloads = s.max_concurrent_downloads;
    });
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
                onchange={() =>
                    setThreadCount(Math.min(32, Math.max(1, threadCount)))}
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
    </div>

    <button
        onclick={handleLogout}
        class="sm:hidden mt-4 w-full text-sm text-th-text-dim hover:text-red-400 border border-th-border
            hover:border-red-800 rounded-xl py-3 transition-colors"
    >
        Logout
    </button>
</div>
