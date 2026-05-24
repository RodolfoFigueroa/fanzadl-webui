<script lang="ts">
    import { goto } from "$app/navigation";
    import {
        clearApiKey,
        getApiKey,
        getLibrary,
        getThreadCount,
        setApiKey,
        setThreadCount,
    } from "$lib/api";

    let apiKey = $state(getApiKey() ?? "");
    let threadCount = $state(getThreadCount());
    let status = $state<"idle" | "testing" | "success" | "error">("idle");
    let errorMessage = $state("");

    async function testAndSave() {
        const trimmed = apiKey.trim();
        if (!trimmed) return;
        setApiKey(trimmed);
        status = "testing";
        errorMessage = "";
        try {
            await getLibrary();
            status = "success";
            setTimeout(() => goto("/"), 800);
        } catch (e) {
            clearApiKey();
            status = "error";
            errorMessage = e instanceof Error ? e.message : "Connection failed";
        }
    }

    function handleKeydown(e: KeyboardEvent) {
        if (e.key === "Enter") testAndSave();
    }
</script>

<svelte:head>
    <title>Settings — FanzaDL</title>
</svelte:head>

<div class="max-w-md mx-auto mt-16">
    <h1 class="text-2xl font-bold mb-6">Settings</h1>
    <div class="bg-th-surface rounded-xl p-6 border border-th-border space-y-4">
        <div>
            <label
                class="block text-sm font-medium text-th-text-muted mb-1.5"
                for="api-key">API Key</label
            >
            <input
                id="api-key"
                type="password"
                bind:value={apiKey}
                placeholder="Enter your API key"
                onkeydown={handleKeydown}
                class="w-full bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-th-text
					placeholder-th-text-faint focus:outline-none focus:ring-2 focus:ring-th-border-strong
					focus:border-transparent transition-shadow"
            />
        </div>

        {#if status === "error"}
            <p class="text-sm text-red-400">{errorMessage}</p>
        {:else if status === "success"}
            <p class="text-sm text-green-400">
                Connected successfully — redirecting…
            </p>
        {/if}

        <button
            onclick={testAndSave}
            disabled={!apiKey.trim() ||
                status === "testing" ||
                status === "success"}
            class="w-full bg-th-accent hover:bg-th-accent-hover disabled:opacity-50
				disabled:cursor-not-allowed text-th-accent-text font-medium py-2 px-4 rounded-lg
				transition-colors"
        >
            {status === "testing" ? "Testing…" : "Save & Test Connection"}
        </button>
    </div>

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
