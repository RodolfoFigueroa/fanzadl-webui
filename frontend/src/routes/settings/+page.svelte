<script lang="ts">
    import { getThreadCount, setThreadCount } from "$lib/api";

    let threadCount = $state(getThreadCount());
</script>

<svelte:head>
    <title>Settings — FanzaDL</title>
</svelte:head>

<div class="max-w-md mx-auto mt-16">
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
                Number of parallel threads used by N_m3u8DL-RE (1–32).
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
    </div>
</div>
