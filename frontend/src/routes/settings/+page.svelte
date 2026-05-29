<script lang="ts">
import cronstrue from 'cronstrue';
import { onMount } from 'svelte';
import { goto } from '$app/navigation';
import {
    getCachedSettings,
    getSettings,
    logout,
    updateSettings,
} from '$lib/api';
import {
    DEFAULT_MULTI_PART_TEMPLATE,
    DEFAULT_SINGLE_PART_TEMPLATE,
    DUMMY_LIBRARY_ITEM,
    renderFilenameTemplate,
} from '$lib/filename';

type Tab = 'download' | 'javstash' | 'filenames' | 'logging' | 'schedule';
let activeTab = $state<Tab>('download');

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
let singlePartTemplate = $state(
    getCachedSettings()?.single_part_filename_template ??
        DEFAULT_SINGLE_PART_TEMPLATE,
);
let multiPartTemplate = $state(
    getCachedSettings()?.multi_part_filename_template ??
        DEFAULT_MULTI_PART_TEMPLATE,
);
let scheduleEnabled = $state(
    getCachedSettings()?.library_refresh_enabled ?? false,
);
let refreshCron = $state(
    getCachedSettings()?.library_refresh_cron ?? '0 0 * * *',
);

let javstashKeyInput = $state('');
let javstashSaving = $state(false);
let javstashError = $state('');

onMount(async () => {
    const s = await getSettings();
    threadCount = s.download_thread_count;
    maxConcurrentDownloads = s.max_concurrent_downloads;
    logLevel = s.log_level;
    javstashEnabled = s.javstash_enabled;
    singlePartTemplate = s.single_part_filename_template;
    multiPartTemplate = s.multi_part_filename_template;
    scheduleEnabled = s.library_refresh_enabled;
    refreshCron = s.library_refresh_cron;
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

const tabs: { id: Tab; label: string }[] = [
    { id: 'download', label: 'Download' },
    { id: 'javstash', label: 'JAVStash' },
    { id: 'filenames', label: 'Filenames' },
    { id: 'logging', label: 'Logging' },
    { id: 'schedule', label: 'Schedule' },
];

const INVALID_CHARS = /[\\:*?"<>|]/;

function validateTemplatePath(rendered: string): string[] {
    const errors: string[] = [];
    if (!rendered.trim()) {
        errors.push('Template must not be empty.');
        return errors;
    }
    if (rendered.startsWith('/'))
        errors.push('Path must not start with a slash.');
    if (rendered.endsWith('/')) errors.push('Path must not end with a slash.');
    if (rendered.includes('//'))
        errors.push('Path contains consecutive slashes (//).');
    if (INVALID_CHARS.test(rendered))
        errors.push(
            'Path contains invalid characters (\\  :  *  ?  "  <  >  |).',
        );
    const segments = rendered.split('/');
    if (segments.some((s) => s === '.' || s === '..'))
        errors.push('Path segments must not be . or ..');
    if (segments.some((s) => s !== s.trim()))
        errors.push('Path segments must not have leading or trailing spaces.');
    return errors;
}

let singlePartErrors = $derived(
    validateTemplatePath(
        renderFilenameTemplate(singlePartTemplate, DUMMY_LIBRARY_ITEM, 0),
    ),
);
let multiPartErrors = $derived(
    validateTemplatePath(
        renderFilenameTemplate(multiPartTemplate, DUMMY_LIBRARY_ITEM, 1),
    ),
);

type CronResult =
    | { ok: true; description: string }
    | { ok: false; error: string };
let cronResult = $derived.by<CronResult>(() => {
    try {
        return { ok: true, description: cronstrue.toString(refreshCron) };
    } catch {
        return { ok: false, error: 'Invalid cron expression' };
    }
});
</script>

<svelte:head>
    <title>Settings — FanzaDL</title>
</svelte:head>

<div class="w-full max-w-2xl mx-auto mt-6 sm:mt-16">
    <h1 class="text-2xl font-bold mb-6">Settings</h1>

    <div class="flex border-b border-th-border mb-0">
        {#each tabs as tab}
            <button
                onclick={() => (activeTab = tab.id)}
                class="px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px
                    {activeTab === tab.id
                        ? 'border-th-border-strong text-th-text'
                        : 'border-transparent text-th-text-muted hover:text-th-text hover:border-th-border'}"
            >
                {tab.label}
            </button>
        {/each}
    </div>

    <div class="bg-th-surface rounded-b-xl rounded-tr-xl p-6 border border-th-border border-t-0 space-y-4">

        {#if activeTab === 'download'}
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
                        maxConcurrentDownloads = Math.max(1, maxConcurrentDownloads);
                        updateSettings({
                            max_concurrent_downloads: maxConcurrentDownloads,
                        });
                    }}
                    class="w-24 bg-th-input border border-th-border-input rounded-lg px-3 py-2 text-th-text
                        focus:outline-none focus:ring-2 focus:ring-th-border-strong focus:border-transparent
                        transition-shadow"
                />
            </div>

        {:else if activeTab === 'javstash'}
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

        {:else if activeTab === 'filenames'}
            <div>
                <label
                    class="block text-sm font-medium text-th-text-muted mb-1.5"
                    for="single-part-template"
                >
                    Single-part filename template
                </label>
                <p class="text-xs text-th-text-dim mb-2">Template for items with a single part.</p>
                <input
                    id="single-part-template"
                    type="text"
                    bind:value={singlePartTemplate}
                    onchange={() => {
                        if (singlePartErrors.length === 0)
                            updateSettings({ single_part_filename_template: singlePartTemplate });
                    }}
                    class="w-full bg-th-input border rounded-lg px-3 py-2 text-th-text font-mono text-sm
                        focus:outline-none focus:ring-2 focus:border-transparent transition-shadow
                        {singlePartErrors.length > 0
                            ? 'border-red-500 focus:ring-red-500'
                            : 'border-th-border-input focus:ring-th-border-strong'}"
                />
                {#if singlePartErrors.length > 0}
                    <ul class="mt-1.5 space-y-0.5">
                        {#each singlePartErrors as error}
                            <li class="text-xs text-red-400">{error}</li>
                        {/each}
                    </ul>
                {:else}
                    <p class="text-xs text-th-text-dim mt-1.5">
                        Preview: <span class="text-th-text font-mono">{renderFilenameTemplate(singlePartTemplate, DUMMY_LIBRARY_ITEM, 0)}.mp4</span>
                    </p>
                {/if}
            </div>
            <div>
                <label
                    class="block text-sm font-medium text-th-text-muted mb-1.5"
                    for="multi-part-template"
                >
                    Multi-part filename template
                </label>
                <p class="text-xs text-th-text-dim mb-2">Template for items with multiple parts.</p>
                <input
                    id="multi-part-template"
                    type="text"
                    bind:value={multiPartTemplate}
                    onchange={() => {
                        if (multiPartErrors.length === 0)
                            updateSettings({ multi_part_filename_template: multiPartTemplate });
                    }}
                    class="w-full bg-th-input border rounded-lg px-3 py-2 text-th-text font-mono text-sm
                        focus:outline-none focus:ring-2 focus:border-transparent transition-shadow
                        {multiPartErrors.length > 0
                            ? 'border-red-500 focus:ring-red-500'
                            : 'border-th-border-input focus:ring-th-border-strong'}"
                />
                {#if multiPartErrors.length > 0}
                    <ul class="mt-1.5 space-y-0.5">
                        {#each multiPartErrors as error}
                            <li class="text-xs text-red-400">{error}</li>
                        {/each}
                    </ul>
                {:else}
                    <p class="text-xs text-th-text-dim mt-1.5">
                        Preview: <span class="text-th-text font-mono">{renderFilenameTemplate(multiPartTemplate, DUMMY_LIBRARY_ITEM, 1)}.mp4</span>
                    </p>
                {/if}
            </div>
            <div class="flex justify-center gap-6 text-xs text-th-text-dim">
                <div>
                    <p class="mb-1">Available fields:</p>
                    <ul class="space-y-0.5">
                        <li><code class="text-th-text">content_id</code></li>
                        <li><code class="text-th-text">content_type</code></li>
                        <li><code class="text-th-text">expire</code></li>
                        <li><code class="text-th-text">mylibrary_id</code></li>
                        <li><code class="text-th-text">part</code></li>
                        <li><code class="text-th-text">purchase_date</code></li>
                        <li><code class="text-th-text">title</code></li>
                        <li><code class="text-th-text">trans_type</code></li>
                        <li class="mt-1.5 text-th-text-dim italic">Requires JAVstash API key:</li>
                        <li><code class="text-th-text">javstash_id</code></li>
                        <li><code class="text-th-text">javstash_studio_code</code></li>
                    </ul>
                </div>
                <div>
                    <p class="mb-1">Format specs:</p>
                    <ul class="space-y-0.5">
                        <li><code class="text-th-text">:U</code> — uppercase</li>
                        <li><code class="text-th-text">:L</code> — lowercase</li>
                        <li><code class="text-th-text">:C</code> — capitalize</li>
                        <li><code class="text-th-text">:T</code> — title case</li>
                        <li><code class="text-th-text">:02</code> — zero-pad to N digits</li>
                        <li><code class="text-th-text">/</code> — subdirectory separator</li>
                    </ul>
                </div>
            </div>

        {:else if activeTab === 'logging'}
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

        {:else if activeTab === 'schedule'}
            <div>
                <label class="flex items-center gap-3 cursor-pointer w-fit">
                    <input
                        type="checkbox"
                        bind:checked={scheduleEnabled}
                        onchange={() =>
                            updateSettings({ library_refresh_enabled: scheduleEnabled })}
                        class="w-4 h-4 rounded border border-th-border-input bg-th-input
                            accent-th-border-strong cursor-pointer"
                    />
                    <span class="text-sm font-medium text-th-text-muted">
                        Enable periodic library refresh
                    </span>
                </label>
                <p class="text-xs text-th-text-dim mt-1.5 mb-4">
                    When enabled, the library is refreshed automatically on the
                    schedule defined below.
                </p>
            </div>
            <div>
                <label
                    class="block text-sm font-medium text-th-text-muted mb-1.5"
                    for="refresh-cron"
                >
                    Refresh schedule
                </label>
                <p class="text-xs text-th-text-dim mb-2">
                    Standard 5-field cron expression
                </p>
                <input
                    id="refresh-cron"
                    type="text"
                    bind:value={refreshCron}
                    disabled={!scheduleEnabled}
                    oninput={() => { /* triggers $derived re-evaluation */ }}
                    onchange={() => {
                        if (cronResult.ok)
                            updateSettings({ library_refresh_cron: refreshCron });
                    }}
                    class="w-full bg-th-input border rounded-lg px-3 py-2 text-th-text font-mono text-sm
                        focus:outline-none focus:ring-2 focus:border-transparent transition-shadow
                        disabled:opacity-50 disabled:cursor-not-allowed
                        {!cronResult.ok && scheduleEnabled
                            ? 'border-red-500 focus:ring-red-500'
                            : 'border-th-border-input focus:ring-th-border-strong'}"
                />
                {#if scheduleEnabled}
                    {#if cronResult.ok}
                        <p class="text-xs text-th-text-dim mt-1.5">
                            {cronResult.description}
                        </p>
                    {:else}
                        <p class="text-xs text-red-400 mt-1.5">{cronResult.error}</p>
                    {/if}
                {/if}
            </div>
        {/if}

    </div>

    <button
        onclick={handleLogout}
        style="cursor: pointer"
        class="sm:hidden mt-4 w-full text-sm text-th-text-dim hover:text-red-400 border border-th-border
            hover:border-red-800 rounded-xl py-3 transition-colors"
    >
        Logout
    </button>
</div>
