<script lang="ts">
import cronstrue from 'cronstrue';
import { onMount } from 'svelte';
import { goto } from '$app/navigation';
import {
    changeAppPassword,
    connectFanza,
    disconnect,
    getApiKey,
    getCachedSettings,
    getSettings,
    logout,
    rotateApiKey,
    testWebhook,
    updateSettings,
} from '$lib/api';
import Button from '$lib/components/Button.svelte';
import FormCheckbox from '$lib/components/FormCheckbox.svelte';
import Select from '$lib/components/Select.svelte';
import TextInput from '$lib/components/TextInput.svelte';
import {
    DEFAULT_MULTI_PART_TEMPLATE,
    DEFAULT_SINGLE_PART_TEMPLATE,
    DUMMY_LIBRARY_ITEM,
    renderFilenameTemplate,
} from '$lib/filename';

type Tab =
    | 'download'
    | 'javstash'
    | 'filenames'
    | 'logging'
    | 'schedule'
    | 'webhook'
    | 'api'
    | 'fanza'
    | 'account';
let activeTab = $state<Tab>('download');

async function handleLogout() {
    try {
        await logout();
    } finally {
        goto('/login');
    }
}

let disconnectConfirming = $state(false);
let disconnecting = $state(false);
let disconnectError = $state('');

let fanzaConnected = $state(getCachedSettings()?.fanza_connected ?? false);
let fanzaUserId = $state<string | null>(
    getCachedSettings()?.fanza_user_id ?? null,
);

let fanzaEmail = $state('');
let fanzaPassword = $state('');
let fanzaConnecting = $state(false);
let fanzaConnectError = $state('');

let currentPassword = $state('');
let newPassword = $state('');
let confirmPassword = $state('');
let passwordSaving = $state(false);
let passwordError = $state('');
let passwordSuccess = $state(false);

let authDisabled = $state(getCachedSettings()?.auth_disabled ?? false);
let authDisabledSaving = $state(false);
let authDisabledError = $state('');

async function handleDisconnect() {
    if (!disconnectConfirming) {
        disconnectConfirming = true;
        return;
    }
    disconnectConfirming = false;
    disconnecting = true;
    disconnectError = '';
    try {
        await disconnect();
        goto('/login');
    } catch (e) {
        disconnectError = e instanceof Error ? e.message : 'Disconnect failed';
    } finally {
        disconnecting = false;
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
let autoDownloadNewItems = $state(
    getCachedSettings()?.auto_download_new_items ?? false,
);
let autoDownloadMissingParts = $state(
    getCachedSettings()?.auto_download_missing_parts ?? false,
);

let webhookUrl = $state(getCachedSettings()?.webhook_url ?? '');
let webhookSecretConfigured = $state(
    getCachedSettings()?.webhook_secret_configured ?? false,
);
let webhookSecretInput = $state('');
let webhookSecretClearing = $state(false);
let webhookEvents = $state<Set<string>>(
    new Set(
        getCachedSettings()?.webhook_events ?? [
            'job_created',
            'job_completed',
            'job_failed',
            'job_cancelled',
            'item_added',
            'item_expired',
        ],
    ),
);
let webhookSaving = $state(false);
let webhookError = $state('');
let webhookTesting = $state(false);
let webhookTestResult = $state<{
    status_code?: number;
    ok?: boolean;
    error?: string;
} | null>(null);

let downloadSaving = $state(false);
let downloadError = $state('');
let filenamesSaving = $state(false);
let filenamesError = $state('');
let loggingSaving = $state(false);
let loggingError = $state('');
let scheduleSaving = $state(false);
let scheduleError = $state('');

const WEBHOOK_EVENT_GROUPS: {
    label: string;
    events: { id: string; label: string }[];
}[] = [
    {
        label: 'Jobs',
        events: [
            { id: 'job_created', label: 'Job created' },
            { id: 'job_completed', label: 'Job completed' },
            { id: 'job_failed', label: 'Job failed' },
            { id: 'job_cancelled', label: 'Job cancelled' },
        ],
    },
    {
        label: 'Library',
        events: [
            { id: 'item_added', label: 'Item added to library' },
            { id: 'item_expired', label: 'Item expired from library' },
        ],
    },
];
let javstashKeyInput = $state('');
let javstashSaving = $state(false);
let javstashError = $state('');

let apiKeyPreview = $state('');
let apiKey = $state<string | null>(null);
let apiKeyPersisted = $state(false);
let apiKeyVisible = $state(false);
let apiKeyRotating = $state(false);
let apiKeyError = $state('');
let apiKeyCopied = $state(false);
let apiKeyConfirming = $state(false);

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
    autoDownloadNewItems = s.auto_download_new_items;
    autoDownloadMissingParts = s.auto_download_missing_parts;
    webhookUrl = s.webhook_url ?? '';
    webhookSecretConfigured = s.webhook_secret_configured;
    webhookEvents = new Set(s.webhook_events);
    fanzaConnected = s.fanza_connected;
    fanzaUserId = s.fanza_user_id;
    authDisabled = s.auth_disabled;

    const k = await getApiKey();
    apiKeyPreview = k.api_key_preview;
    apiKeyPersisted = k.persisted;
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

async function handleRotateApiKey() {
    if (!apiKeyConfirming) {
        apiKeyConfirming = true;
        return;
    }
    apiKeyConfirming = false;
    apiKeyRotating = true;
    apiKeyError = '';
    try {
        const k = await rotateApiKey();
        apiKey = k.api_key;
        apiKeyPreview = k.api_key_preview;
        apiKeyPersisted = k.persisted;
        apiKeyVisible = false;
    } catch (e) {
        apiKeyError =
            e instanceof Error ? e.message : 'Failed to rotate API key';
    } finally {
        apiKeyRotating = false;
    }
}

async function handleCopyApiKey() {
    if (apiKey === null) return;
    try {
        await navigator.clipboard.writeText(apiKey);
        apiKeyCopied = true;
        setTimeout(() => (apiKeyCopied = false), 2000);
    } catch {
        // clipboard access denied — silently ignore
    }
}

const tabs: { id: Tab; label: string }[] = [
    { id: 'download', label: 'Download' },
    { id: 'javstash', label: 'JAVStash' },
    { id: 'filenames', label: 'Filenames' },
    { id: 'logging', label: 'Logging' },
    { id: 'schedule', label: 'Schedule' },
    { id: 'webhook', label: 'Webhooks' },
    { id: 'api', label: 'API' },
    { id: 'fanza', label: 'Fanza' },
    { id: 'account', label: 'Account' },
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

<div class="w-full max-w-3xl mx-auto mt-6 sm:mt-16">
    <h1 class="text-2xl font-bold mb-6">Settings</h1>

    <div class="flex flex-col sm:flex-row sm:gap-6">

        <!-- Mobile: horizontal scrollable tab bar -->
        <div class="sm:hidden flex overflow-x-auto scrollbar-none border-b border-th-border mb-0">
            {#each tabs as tab}
                <button
                    onclick={() => (activeTab = tab.id)}
                    class="px-4 py-2 text-sm font-medium transition-colors border-b-2 -mb-px whitespace-nowrap flex-shrink-0
                        {activeTab === tab.id
                            ? 'border-th-border-strong text-th-text'
                            : 'border-transparent text-th-text-muted hover:text-th-text hover:border-th-border'}"
                >
                    {tab.label}
                </button>
            {/each}
        </div>

        <!-- Desktop: vertical sidebar -->
        <nav class="hidden sm:flex flex-col w-36 shrink-0 gap-0.5 pt-1">
            {#each tabs as tab}
                <button
                    onclick={() => (activeTab = tab.id)}
                    class="w-full text-left px-3 py-2 text-sm rounded-lg transition-colors border-l-2
                        {activeTab === tab.id
                            ? 'border-th-border-strong bg-th-border/20 text-th-text font-medium'
                            : 'border-transparent text-th-text-muted hover:text-th-text hover:bg-th-border/10'}"
                >
                    {tab.label}
                </button>
            {/each}
        </nav>

        <!-- Content panel -->
        <div class="bg-th-surface rounded-b-xl rounded-tr-xl sm:rounded-xl p-6 border border-th-border border-t-0 sm:border-t space-y-4 flex-1 min-w-0">

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
                <TextInput
                    id="thread-count"
                    type="number"
                    min="1"
                    max="32"
                    bind:value={threadCount}
                    onchange={() => {
                        threadCount = Math.min(32, Math.max(1, threadCount));
                    }}
                    class="w-24"
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
                <TextInput
                    id="max-concurrent-downloads"
                    type="number"
                    min="1"
                    bind:value={maxConcurrentDownloads}
                    onchange={() => {
                        maxConcurrentDownloads = Math.max(1, maxConcurrentDownloads);
                    }}
                    class="w-24"
                />
            </div>
            {#if downloadError}
                <p class="text-xs text-red-400">{downloadError}</p>
            {/if}
            <div class="pt-1">
                <Button
                    onclick={async () => {
                        downloadSaving = true;
                        downloadError = '';
                        try {
                            await updateSettings({
                                download_thread_count: threadCount,
                                max_concurrent_downloads: maxConcurrentDownloads,
                            });
                        } catch (e) {
                            downloadError = e instanceof Error ? e.message : 'Failed to save';
                        } finally {
                            downloadSaving = false;
                        }
                    }}
                    loading={downloadSaving}
                    loadingText="Saving…"
                >Save</Button>
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
                    <TextInput
                        id="javstash-api-key"
                        type="password"
                        placeholder="Enter new API key"
                        bind:value={javstashKeyInput}
                        disabled={javstashSaving}
                        class="flex-1"
                    />
                    <Button
                        variant="secondary"
                        onclick={handleSaveJavstashKey}
                        loading={javstashSaving}
                        disabled={!javstashKeyInput.trim()}
                        loadingText="Saving…"
                    >Save</Button>
                    {#if javstashEnabled}
                        <Button
                            variant="ghost-destructive"
                            onclick={handleClearJavstashKey}
                            disabled={javstashSaving}
                        >Clear</Button>
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
                <TextInput
                    id="single-part-template"
                    type="text"
                    bind:value={singlePartTemplate}
                    error={singlePartErrors.length > 0}
                    class="w-full font-mono"
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
                <TextInput
                    id="multi-part-template"
                    type="text"
                    bind:value={multiPartTemplate}
                    error={multiPartErrors.length > 0}
                    class="w-full font-mono"
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
            {#if filenamesError}
                <p class="text-xs text-red-400">{filenamesError}</p>
            {/if}
            <div class="pt-1">
                <Button
                    onclick={async () => {
                        filenamesSaving = true;
                        filenamesError = '';
                        try {
                            await updateSettings({
                                single_part_filename_template: singlePartTemplate,
                                multi_part_filename_template: multiPartTemplate,
                            });
                        } catch (e) {
                            filenamesError = e instanceof Error ? e.message : 'Failed to save';
                        } finally {
                            filenamesSaving = false;
                        }
                    }}
                    loading={filenamesSaving}
                    disabled={singlePartErrors.length > 0 || multiPartErrors.length > 0}
                    loadingText="Saving…"
                >Save</Button>
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
                    Controls the verbosity of server-side logging.
                </p>
                <Select
                    id="log-level"
                    bind:value={logLevel}
                    class="w-32"
                >
                    <option value="DEBUG">DEBUG</option>
                    <option value="INFO">INFO</option>
                    <option value="WARNING">WARNING</option>
                    <option value="ERROR">ERROR</option>
                </Select>
            </div>
            {#if loggingError}
                <p class="text-xs text-red-400">{loggingError}</p>
            {/if}
            <div class="pt-1">
                <Button
                    onclick={async () => {
                        loggingSaving = true;
                        loggingError = '';
                        try {
                            await updateSettings({ log_level: logLevel });
                        } catch (e) {
                            loggingError = e instanceof Error ? e.message : 'Failed to save';
                        } finally {
                            loggingSaving = false;
                        }
                    }}
                    loading={loggingSaving}
                    loadingText="Saving…"
                >Save</Button>
            </div>

        {:else if activeTab === 'schedule'}
            <div>
                <label class="flex items-center gap-3 cursor-pointer w-fit">
                    <FormCheckbox bind:checked={autoDownloadNewItems} />
                    <span class="text-sm font-medium text-th-text-muted">
                        Auto-download new items
                    </span>
                </label>
                <p class="text-xs text-th-text-dim mt-1.5 mb-4">
                    When enabled, items that appear in the library after a refresh (manual or
                    scheduled) are automatically added to the download queue at the highest
                    available quality.
                </p>
            </div>
            <div>
                <label class="flex items-center gap-3 cursor-pointer w-fit">
                    <FormCheckbox bind:checked={autoDownloadMissingParts} />
                    <span class="text-sm font-medium text-th-text-muted">
                        Auto-download missing parts
                    </span>
                </label>
                <p class="text-xs text-th-text-dim mt-1.5 mb-4">
                    When enabled, any parts missing from the download directory are
                    automatically queued after each library refresh, at the highest available quality.
                </p>
            </div>
            <div>
                <label class="flex items-center gap-3 cursor-pointer w-fit">
                    <FormCheckbox bind:checked={scheduleEnabled} />
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
                <TextInput
                    id="refresh-cron"
                    type="text"
                    bind:value={refreshCron}
                    disabled={!scheduleEnabled}
                    oninput={() => { /* triggers $derived re-evaluation */ }}
                    error={!cronResult.ok && scheduleEnabled}
                    class="w-full font-mono"
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
            {#if scheduleError}
                <p class="text-xs text-red-400">{scheduleError}</p>
            {/if}
            <div class="pt-1">
                <Button
                    onclick={async () => {
                        scheduleSaving = true;
                        scheduleError = '';
                        try {
                            await updateSettings({
                                auto_download_new_items: autoDownloadNewItems,
                                auto_download_missing_parts: autoDownloadMissingParts,
                                library_refresh_enabled: scheduleEnabled,
                                library_refresh_cron: refreshCron,
                            });
                        } catch (e) {
                            scheduleError = e instanceof Error ? e.message : 'Failed to save';
                        } finally {
                            scheduleSaving = false;
                        }
                    }}
                    loading={scheduleSaving}
                    disabled={scheduleEnabled && !cronResult.ok}
                    loadingText="Saving…"
                >Save</Button>
            </div>

        {:else if activeTab === 'webhook'}
            <div>
                <label
                    class="block text-sm font-medium text-th-text-muted mb-1.5"
                    for="webhook-url"
                >
                    Webhook URL
                </label>
                <p class="text-xs text-th-text-dim mb-2">
                    POST notifications will be sent to this URL for the selected events.
                    Leave blank to disable webhooks.
                </p>
                <div class="flex gap-2">
                    <TextInput
                        id="webhook-url"
                        type="url"
                        placeholder="https://example.com/webhook"
                        bind:value={webhookUrl}
                        class="flex-1"
                    />
                </div>
            </div>
            <div>
                <p class="text-sm font-medium text-th-text-muted mb-1.5">Webhook secret</p>
                <p class="text-xs text-th-text-dim mb-2">
                    Optional HMAC-SHA256 signing secret. When set, each request includes an
                    <code class="text-th-text">X-Webhook-Signature: sha256=&lt;hex&gt;</code> header.
                </p>
                {#if webhookSecretConfigured && !webhookSecretClearing}
                    <div class="flex items-center gap-3">
                        <span class="text-xs text-th-text-dim">Secret configured</span>
                        <Button
                            variant="ghost-destructive"
                            size="sm"
                            onclick={() => (webhookSecretClearing = true)}
                        >Clear secret</Button>
                    </div>
                {:else}
                    <TextInput
                        type="password"
                        placeholder={webhookSecretClearing ? 'Leave blank to clear, or enter a new secret' : 'Enter a secret to enable signing'}
                        bind:value={webhookSecretInput}
                        class="w-full"
                    />
                    {#if webhookSecretClearing}
                        <p class="text-xs text-th-text-dim mt-1">
                            Enter a new secret or leave blank to remove signing.
                        </p>
                    {/if}
                {/if}
            </div>
            <div>
                <p class="text-sm font-medium text-th-text-muted mb-1.5">Events</p>
                <p class="text-xs text-th-text-dim mb-2">Choose which events trigger a webhook delivery.</p>
                <div class="space-y-4">
                    {#each WEBHOOK_EVENT_GROUPS as group}
                        {@const groupIds = group.events.map(e => e.id)}
                        {@const allChecked = groupIds.every(id => webhookEvents.has(id))}
                        {@const someChecked = !allChecked && groupIds.some(id => webhookEvents.has(id))}
                        <div>
                            <label class="flex items-center gap-3 cursor-pointer w-fit mb-2">
                                <FormCheckbox
                                    checked={allChecked}
                                    indeterminate={someChecked}
                                    onchange={() => {
                                        const next = new Set(webhookEvents);
                                        if (allChecked) {
                                            groupIds.forEach(id => next.delete(id));
                                        } else {
                                            groupIds.forEach(id => next.add(id));
                                        }
                                        webhookEvents = next;
                                    }}
                                />
                                <span class="text-sm font-semibold text-th-text-muted">{group.label}</span>
                            </label>
                            <div class="space-y-2 pl-7">
                                {#each group.events as ev}
                                    <label class="flex items-center gap-3 cursor-pointer w-fit">
                                        <FormCheckbox
                                            checked={webhookEvents.has(ev.id)}
                                            onchange={() => {
                                                const next = new Set(webhookEvents);
                                                if (next.has(ev.id)) next.delete(ev.id); else next.add(ev.id);
                                                webhookEvents = next;
                                            }}
                                        />
                                        <span class="text-sm text-th-text-muted">{ev.label}</span>
                                    </label>
                                {/each}
                            </div>
                        </div>
                    {/each}
                </div>
            </div>
            {#if webhookError}
                <p class="text-xs text-red-400">{webhookError}</p>
            {/if}
            {#if webhookTestResult !== null}
                {#if webhookTestResult.error}
                    <p class="text-xs text-red-400">Test failed: {webhookTestResult.error}</p>
                {:else if webhookTestResult.ok}
                    <p class="text-xs text-green-400">Test succeeded (HTTP {webhookTestResult.status_code})</p>
                {:else}
                    <p class="text-xs text-amber-400">Test sent but server returned HTTP {webhookTestResult.status_code}</p>
                {/if}
            {/if}
            <div class="flex gap-3 pt-1">
                <Button
                    onclick={async () => {
                        webhookSaving = true;
                        webhookError = '';
                        webhookTestResult = null;
                        try {
                            const patch: Record<string, unknown> = {
                                webhook_url: webhookUrl.trim() || null,
                                webhook_events: [...webhookEvents],
                            };
                            if (webhookSecretClearing) {
                                patch.webhook_secret = webhookSecretInput.trim() || null;
                            } else if (webhookSecretInput.trim()) {
                                patch.webhook_secret = webhookSecretInput.trim();
                            }
                            const s = await updateSettings(patch as never);
                            webhookUrl = s.webhook_url ?? '';
                            webhookSecretConfigured = s.webhook_secret_configured;
                            webhookSecretInput = '';
                            webhookSecretClearing = false;
                        } catch (e) {
                            webhookError = e instanceof Error ? e.message : 'Failed to save';
                        } finally {
                            webhookSaving = false;
                        }
                    }}
                    loading={webhookSaving}
                    loadingText="Saving…"
                >Save</Button>
                <Button
                    variant="secondary"
                    onclick={async () => {
                        webhookTesting = true;
                        webhookTestResult = null;
                        try {
                            webhookTestResult = await testWebhook(webhookUrl.trim());
                        } catch (e) {
                            webhookTestResult = { error: e instanceof Error ? e.message : 'Request failed' };
                        } finally {
                            webhookTesting = false;
                        }
                    }}
                    loading={webhookTesting}
                    disabled={!webhookUrl.trim()}
                    loadingText="Testing…"
                >Test</Button>
            </div>

        {:else if activeTab === 'api'}
            <div>
                <label
                    class="block text-sm font-medium text-th-text-muted mb-1.5"
                    for="local-api-key"
                >
                    API key
                </label>
                <p class="text-xs text-th-text-dim mb-2">
                    Use this key to authenticate external clients connecting to notification
                    or other API endpoints. The key is generated automatically and stored
                    encrypted on the server.
                </p>
                {#if !apiKeyPersisted}
                    <p class="text-xs text-amber-400 mb-2">
                        TOKEN_ENCRYPTION_KEY is not set — this key is ephemeral and will
                        change on every server restart.
                    </p>
                {/if}
                <TextInput
                    id="local-api-key"
                    type="text"
                    readonly
                    value={apiKeyPreview}
                    class="w-full font-mono mb-2"
                />
                {#if apiKey !== null}
                    <div class="mb-2 p-3 rounded-lg border border-amber-700/50 bg-amber-900/10 space-y-2">
                        <p class="text-xs text-amber-400">
                            New key — copy it now, it will not be shown again.
                        </p>
                        <div class="flex gap-2">
                            <div class="relative flex-1">
                                <TextInput
                                    type={apiKeyVisible ? 'text' : 'password'}
                                    readonly
                                    value={apiKey}
                                    class="w-full font-mono pr-10 select-all"
                                />
                                <button
                                    onclick={() => (apiKeyVisible = !apiKeyVisible)}
                                    class="absolute right-2 top-1/2 -translate-y-1/2 text-th-text-dim
                                        hover:text-th-text transition-colors"
                                    aria-label={apiKeyVisible ? 'Hide key' : 'Show key'}
                                >
                                    {#if apiKeyVisible}
                                        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                            <path stroke-linecap="round" stroke-linejoin="round" d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
                                        </svg>
                                    {:else}
                                        <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                                            <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                            <path stroke-linecap="round" stroke-linejoin="round" d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                                        </svg>
                                    {/if}
                                </button>
                            </div>
                            <Button
                                variant="secondary"
                                onclick={handleCopyApiKey}
                                class="min-w-[4.5rem]"
                            >{apiKeyCopied ? 'Copied!' : 'Copy'}</Button>
                        </div>
                    </div>
                {/if}
                {#if apiKeyConfirming}
                    <div class="mt-2 space-y-2">
                        <p class="text-xs text-amber-400">
                            Rotating will invalidate the current key. Existing clients will stop working.
                        </p>
                        <div class="flex gap-2">
                            <Button
                                variant="destructive"
                                size="sm"
                                onclick={handleRotateApiKey}
                                loading={apiKeyRotating}
                                loadingText="Rotating…"
                            >Confirm rotate</Button>
                            <Button
                                variant="secondary"
                                size="sm"
                                onclick={() => (apiKeyConfirming = false)}
                            >Cancel</Button>
                        </div>
                    </div>
                {:else}
                    <Button
                        variant="ghost-destructive"
                        class="mt-1"
                        onclick={handleRotateApiKey}
                        disabled={apiKeyRotating}
                    >Rotate key</Button>
                {/if}
                {#if apiKeyError}
                    <p class="text-xs text-red-400 mt-1">{apiKeyError}</p>
                {/if}
            </div>

        {:else if activeTab === 'fanza'}
            <div>
                <p class="text-sm font-medium text-th-text-muted mb-1">Fanza account</p>
                {#if fanzaConnected}
                    <p class="text-xs text-th-text-dim mb-3">
                        Connected as <span class="text-th-text font-mono">{fanzaUserId}</span>
                    </p>
                    {#if disconnectConfirming}
                        <div class="space-y-2">
                            <p class="text-xs text-amber-400">This will cancel all downloads and wipe the library. Are you sure?</p>
                            <div class="flex gap-2">
                                <button
                                    onclick={handleDisconnect}
                                    disabled={disconnecting}
                                    class="px-3 py-1.5 text-xs rounded-lg border border-red-800 text-red-400
                                        hover:bg-red-900/20 transition-colors disabled:opacity-40 whitespace-nowrap"
                                >
                                    {disconnecting ? 'Disconnecting…' : 'Confirm disconnect'}
                                </button>
                                <button
                                    onclick={() => (disconnectConfirming = false)}
                                    class="px-3 py-1.5 text-xs rounded-lg border border-th-border
                                        text-th-text-dim hover:text-th-text transition-colors whitespace-nowrap"
                                >
                                    Cancel
                                </button>
                            </div>
                        </div>
                    {:else}
                        <button
                            onclick={handleDisconnect}
                            class="px-3 py-2 text-sm rounded-lg border border-th-border
                                hover:border-red-800 text-th-text-dim hover:text-red-400
                                transition-colors"
                        >
                            Disconnect Fanza account
                        </button>
                    {/if}
                    {#if disconnectError}
                        <p class="text-xs text-red-400 mt-1">{disconnectError}</p>
                    {/if}
                {:else}
                    <p class="text-xs text-th-text-dim mb-3">Not connected. Enter your Fanza credentials to connect.</p>
                    <div class="flex flex-col gap-3">
                        <div class="flex flex-col gap-1">
                            <label for="fanza-email" class="text-xs font-medium text-th-text-muted">Email</label>
                            <TextInput
                                id="fanza-email"
                                type="email"
                                bind:value={fanzaEmail}
                                autocomplete="email"
                                disabled={fanzaConnecting}
                            />
                        </div>
                        <div class="flex flex-col gap-1">
                            <label for="fanza-password" class="text-xs font-medium text-th-text-muted">Password</label>
                            <TextInput
                                id="fanza-password"
                                type="password"
                                bind:value={fanzaPassword}
                                autocomplete="current-password"
                                disabled={fanzaConnecting}
                            />
                        </div>
                        {#if fanzaConnectError}
                            <p class="text-xs text-red-400">{fanzaConnectError}</p>
                        {/if}
                        <div>
                            <button
                                onclick={async () => {
                                    fanzaConnecting = true;
                                    fanzaConnectError = '';
                                    try {
                                        await connectFanza(fanzaEmail, fanzaPassword);
                                        const s = await getSettings();
                                        fanzaConnected = s.fanza_connected;
                                        fanzaUserId = s.fanza_user_id;
                                        fanzaEmail = '';
                                        fanzaPassword = '';
                                    } catch (e) {
                                        fanzaConnectError = e instanceof Error ? e.message : 'Connect failed';
                                    } finally {
                                        fanzaConnecting = false;
                                    }
                                }}
                                disabled={fanzaConnecting || !fanzaEmail.trim() || !fanzaPassword.trim()}
                                class="px-4 py-2 text-sm rounded-lg border border-th-border-strong
                                    text-th-text hover:bg-th-border/20 transition-colors disabled:opacity-40"
                            >
                                {fanzaConnecting ? 'Connecting…' : 'Connect'}
                            </button>
                        </div>
                    </div>
                {/if}
            </div>

        {:else if activeTab === 'account'}
            <div>
                <p class="text-sm font-medium text-th-text-muted mb-1.5">Authentication</p>
                <label class="flex items-start gap-3 cursor-pointer w-fit mb-2">
                    <FormCheckbox bind:checked={authDisabled} class="mt-0.5" />
                    <span class="text-sm text-th-text-muted">Disable password authentication</span>
                </label>
                <p class="text-xs text-th-text-dim mb-2">
                    When enabled, anyone who can reach this app can access it without a password.
                    API key authentication is unaffected.
                </p>
                {#if authDisabled}
                    <p class="text-xs text-amber-400 mb-2">
                        Warning: the app is currently open to anyone on the network.
                    </p>
                {/if}
                {#if authDisabledError}
                    <p class="text-xs text-red-400 mb-2">{authDisabledError}</p>
                {/if}
                <Button
                    onclick={async () => {
                        authDisabledSaving = true;
                        authDisabledError = '';
                        try {
                            await updateSettings({ auth_disabled: authDisabled });
                        } catch (e) {
                            authDisabledError = e instanceof Error ? e.message : 'Failed to save';
                        } finally {
                            authDisabledSaving = false;
                        }
                    }}
                    loading={authDisabledSaving}
                    loadingText="Saving…"
                >Save</Button>
            </div>

            <div class="border-t border-th-border pt-4">
                <p class="text-sm font-medium text-th-text-muted mb-1.5">App password</p>
                <p class="text-xs text-th-text-dim mb-3">Change the password used to log in to this app.</p>
                <div class="flex flex-col gap-3">
                    <div class="flex flex-col gap-1">
                        <label for="current-password" class="text-xs font-medium text-th-text-muted">Current password</label>
                        <TextInput
                            id="current-password"
                            type="password"
                            bind:value={currentPassword}
                            autocomplete="current-password"
                            disabled={passwordSaving}
                        />
                    </div>
                    <div class="flex flex-col gap-1">
                        <label for="new-password" class="text-xs font-medium text-th-text-muted">New password</label>
                        <TextInput
                            id="new-password"
                            type="password"
                            bind:value={newPassword}
                            autocomplete="new-password"
                            disabled={passwordSaving}
                        />
                    </div>
                    <div class="flex flex-col gap-1">
                        <label for="confirm-password" class="text-xs font-medium text-th-text-muted">Confirm new password</label>
                        <TextInput
                            id="confirm-password"
                            type="password"
                            bind:value={confirmPassword}
                            autocomplete="new-password"
                            disabled={passwordSaving}
                        />
                    </div>
                    {#if passwordError}
                        <p class="text-xs text-red-400">{passwordError}</p>
                    {/if}
                    {#if passwordSuccess}
                        <p class="text-xs text-green-400">Password changed successfully.</p>
                    {/if}
                    <div>
                        <button
                            onclick={async () => {
                                if (newPassword !== confirmPassword) {
                                    passwordError = 'New passwords do not match.';
                                    return;
                                }
                                passwordSaving = true;
                                passwordError = '';
                                passwordSuccess = false;
                                try {
                                    await changeAppPassword(currentPassword, newPassword);
                                    currentPassword = '';
                                    newPassword = '';
                                    confirmPassword = '';
                                    passwordSuccess = true;
                                } catch (e) {
                                    passwordError = e instanceof Error ? e.message : 'Failed to change password';
                                } finally {
                                    passwordSaving = false;
                                }
                            }}
                            disabled={passwordSaving || !currentPassword || !newPassword || !confirmPassword}
                            class="px-4 py-2 text-sm rounded-lg border border-th-border-strong
                                text-th-text hover:bg-th-border/20 transition-colors disabled:opacity-40"
                        >
                            {passwordSaving ? 'Saving…' : 'Change password'}
                        </button>
                    </div>
                </div>
            </div>
        {/if}

    </div>

    </div><!-- end flex row wrapper -->

    {#if !authDisabled}
        <Button
            variant="ghost-destructive"
            class="sm:hidden mt-4 w-full"
            onclick={handleLogout}
        >Logout</Button>
    {/if}
</div>
