<script lang="ts">
import { onMount, untrack } from 'svelte';
import { goto } from '$app/navigation';
import {
    checkFilename,
    getCachedSettings,
    getJobs,
    getStreams,
    startDownload,
} from '$lib/api';
import {
    DEFAULT_MULTI_PART_TEMPLATE,
    DEFAULT_SINGLE_PART_TEMPLATE,
    renderFilenameTemplate,
} from '$lib/filename';
import type { DownloadJob, LibraryItem, StreamVariant } from '$lib/types';

let {
    item,
    onClose,
}: {
    item: LibraryItem;
    onClose: () => void;
} = $props();

function formatBandwidth(bps: number): string {
    if (bps >= 1_000_000) return `${(bps / 1_000_000).toFixed(1)} Mbps`;
    if (bps >= 1_000) return `${(bps / 1_000).toFixed(0)} Kbps`;
    return `${bps} bps`;
}

// Use untrack to explicitly capture initial prop values (modal is never re-used with a different item)
// parts=0 means a single part accessed via index 0; parts>=1 are 1-indexed
const partNumbers = untrack(() =>
    item.parts === 0
        ? [0]
        : Array.from({ length: item.parts }, (_, i) => i + 1),
);

const _isSinglePart = partNumbers.length === 1;
const _template = untrack(() =>
    _isSinglePart
        ? (getCachedSettings()?.single_part_filename_template ??
          DEFAULT_SINGLE_PART_TEMPLATE)
        : (getCachedSettings()?.multi_part_filename_template ??
          DEFAULT_MULTI_PART_TEMPLATE),
);

let enabledParts = $state<boolean[]>(partNumbers.map(() => true));

let streamsPerPart = $state<StreamVariant[][]>(partNumbers.map(() => []));
let selectedPerPart = $state<StreamVariant[]>(
    partNumbers.map(() => ({}) as StreamVariant),
);
let streamsAreUniform = $state(false);
let showPerPart = $state(false);
let sharedSelected = $state<StreamVariant>({} as StreamVariant);

$effect(() => {
    if (streamsAreUniform && !showPerPart && sharedSelected.bandwidth != null) {
        selectedPerPart = streamsPerPart.map(
            (variants) =>
                variants.find((v) => v.index === sharedSelected.index) ??
                sharedSelected,
        );
    }
});
let filenamesPerPart = $state<string[]>(
    partNumbers.map((p) => renderFilenameTemplate(_template, item, p)),
);

let loadingStreams = $state(true);
let streamError = $state('');
let submitting = $state(false);
let submitError = $state('');
let copiedPerPart = $state<boolean[]>(partNumbers.map(() => false));

let activeJobs = $state<DownloadJob[]>([]);
let fileExistsPerPart = $state<boolean[]>(partNumbers.map(() => false));

async function copyUrl(i: number) {
    const uri = selectedPerPart[i]?.uri;
    if (!uri) return;
    await navigator.clipboard.writeText(uri);
    const updated = [...copiedPerPart];
    updated[i] = true;
    copiedPerPart = updated;
    setTimeout(() => {
        const reset = [...copiedPerPart];
        reset[i] = false;
        copiedPerPart = reset;
    }, 2000);
}

let enabledCount = $derived(enabledParts.filter(Boolean).length);
let allEnabled = $derived(enabledCount === partNumbers.length);

let filenameErrors = $derived(
    partNumbers.map((_, i) => {
        if (!enabledParts[i]) return '';
        const name = filenamesPerPart[i];
        if (!name) return '';
        if (
            activeJobs.some(
                (j) =>
                    (j.status === 'pending' || j.status === 'running') &&
                    j.output_name === name,
            )
        )
            return 'This filename is already in the download queue.';
        if (
            partNumbers.some(
                (_, j) =>
                    j !== i && enabledParts[j] && filenamesPerPart[j] === name,
            )
        )
            return 'This filename is used by another part in this download.';
        return '';
    }),
);

let canSubmit = $derived(
    !loadingStreams &&
        !streamError &&
        !submitting &&
        enabledCount > 0 &&
        partNumbers.every(
            (_, i) => !enabledParts[i] || selectedPerPart[i]?.bandwidth != null,
        ) &&
        filenameErrors.every((e, i) => !enabledParts[i] || !e),
);

let hasAnyConflict = $derived(
    partNumbers.some(
        (_, i) =>
            enabledParts[i] && (!!filenameErrors[i] || fileExistsPerPart[i]),
    ),
);

let selectedIndexPerPart = $derived(
    partNumbers.map((_, i) =>
        streamsPerPart[i].findIndex(
            (v) => v.index === selectedPerPart[i]?.index,
        ),
    ),
);

onMount(async () => {
    void getJobs()
        .then((jobs) => {
            activeJobs = jobs;
        })
        .catch(() => {
            // best-effort; silently ignore
        });

    // Check which parts already exist on disk (one-shot, filenames are fixed)
    void Promise.all(
        filenamesPerPart.map((name) =>
            checkFilename(name)
                .then(({ file_exists }) => file_exists)
                .catch(() => false),
        ),
    ).then((results) => {
        fileExistsPerPart = results;
    });

    try {
        const results: StreamVariant[][] = [];
        for (const p of partNumbers) {
            results.push(await getStreams(item.mylibrary_id, p));
            if (partNumbers.length > 1)
                await new Promise((r) => setTimeout(r, 500));
        }
        streamsPerPart = results.map((variants) =>
            [...variants].sort((a, b) => b.bandwidth - a.bandwidth),
        );
        selectedPerPart = streamsPerPart.map(
            (variants) => variants[0] ?? ({} as StreamVariant),
        );
        if (streamsPerPart.length > 1) {
            const ref = streamsPerPart[0];
            streamsAreUniform = streamsPerPart.every(
                (variants) =>
                    variants.length === ref.length &&
                    variants.every(
                        (v, idx) =>
                            v.index === ref[idx].index &&
                            v.bandwidth === ref[idx].bandwidth &&
                            v.codecs === ref[idx].codecs,
                    ),
            );
            if (streamsAreUniform) {
                sharedSelected = streamsPerPart[0][0] ?? ({} as StreamVariant);
            }
        }
    } catch (e) {
        streamError =
            e instanceof Error ? e.message : 'Failed to fetch stream variants';
    } finally {
        loadingStreams = false;
    }
});

async function handleSubmit() {
    submitting = true;
    submitError = '';
    try {
        await Promise.all(
            partNumbers.flatMap((_, i) =>
                enabledParts[i]
                    ? [
                          startDownload(
                              item.mylibrary_id,
                              partNumbers[i],
                              selectedPerPart[i].index,
                              filenamesPerPart[i],
                          ),
                      ]
                    : [],
            ),
        );
        onClose();
        goto('/downloads');
    } catch (e) {
        submitError =
            e instanceof Error ? e.message : 'Failed to start download';
        submitting = false;
    }
}

function deselectExisting() {
    enabledParts = partNumbers.map(
        (_, i) =>
            enabledParts[i] && !filenameErrors[i] && !fileExistsPerPart[i],
    );
}

function handleBackdropClick(e: MouseEvent) {
    if (e.target === e.currentTarget) onClose();
}

function handleKeydown(e: KeyboardEvent) {
    if (e.key === 'Escape') onClose();
}
</script>

<!-- Backdrop -->
<div
    class="fixed inset-0 bg-black/70 backdrop-blur-sm flex items-center justify-center z-50 p-4"
    role="dialog"
    aria-modal="true"
    aria-label="Download {item.title}"
    onclick={handleBackdropClick}
    onkeydown={handleKeydown}
    tabindex="-1"
>
    <!-- Dialog panel -->
    <div
        class="bg-th-surface rounded-xl border border-th-border-input w-full max-w-lg max-h-[90vh]
			flex flex-col overflow-hidden shadow-2xl"
    >
        <!-- Header -->
        <div
            class="flex items-start justify-between p-4 border-b border-th-border"
        >
            <h2 class="text-base font-semibold leading-snug pr-4 line-clamp-2">
                {item.title}
            </h2>
            <button
                onclick={onClose}
                class="text-th-text-dim hover:text-th-text transition-colors flex-shrink-0 mt-0.5"
                aria-label="Close"
            >
                <svg
                    class="w-5 h-5"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M6 18L18 6M6 6l12 12"
                    />
                </svg>
            </button>
        </div>

        <!-- Scrollable body -->
        <div class="flex-1 overflow-y-auto p-4 space-y-3">
            {#if loadingStreams}
                <div class="text-center text-th-text-dim py-10">
                    <svg
                        class="w-6 h-6 animate-spin mx-auto mb-2"
                        fill="none"
                        stroke="currentColor"
                        viewBox="0 0 24 24"
                    >
                        <path
                            stroke-linecap="round"
                            stroke-linejoin="round"
                            stroke-width="2"
                            d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                        />
                    </svg>
                    Loading stream variants…
                </div>
            {:else if streamError}
                <p class="text-red-400 text-sm">{streamError}</p>
            {:else}
                {#if partNumbers.length > 1}
                    <div class="flex justify-end gap-2">
                        <button
                            onclick={deselectExisting}
                            disabled={!hasAnyConflict}
                            class="text-xs font-medium py-1 px-2.5 rounded-md bg-th-input
								hover:bg-th-input-nested text-th-text-muted
								disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                            Deselect all existing
                        </button>
                        <button
                            onclick={() =>
                                (enabledParts = partNumbers.map(
                                    () => !allEnabled,
                                ))}
                            class="text-xs font-medium py-1 px-2.5 rounded-md bg-th-input
								hover:bg-th-input-nested text-th-text-muted transition-colors"
                        >
                            {allEnabled ? "Deselect all" : "Select all"}
                        </button>
                    </div>
                {/if}
                {#if streamsAreUniform}
                    <div class="bg-th-input rounded-lg p-3 space-y-2">
                        <div class="flex items-center justify-between">
                            <label
                                for="quality-shared"
                                class="text-xs text-th-text-dim"
                                >Quality (all parts)</label
                            >
                            <label
                                class="flex items-center gap-1.5 cursor-pointer select-none"
                            >
                                <input
                                    type="checkbox"
                                    bind:checked={showPerPart}
                                    class="accent-sakura-400 w-3.5 h-3.5 cursor-pointer"
                                />
                                <span class="text-xs text-th-text-dim"
                                    >Per-part settings</span
                                >
                            </label>
                        </div>
                        {#if !showPerPart}
                            <select
                                id="quality-shared"
                                class="w-full bg-th-input-nested border border-th-border-input rounded-lg px-2 py-1.5
								text-sm text-th-text focus:outline-none focus:ring-2 focus:ring-th-border-strong"
                                onchange={(e) => {
                                    const idx = parseInt(
                                        (e.target as HTMLSelectElement).value,
                                    );
                                    sharedSelected = streamsPerPart[0][idx];
                                }}
                            >
                                {#each streamsPerPart[0] as variant, vi}
                                    <option value={vi}>
                                        {formatBandwidth(variant.bandwidth)}
                                    </option>
                                {/each}
                            </select>
                        {/if}
                    </div>
                {/if}
                {#each partNumbers as part, i}
                    <div
                        class="bg-th-input rounded-lg p-3 space-y-3 transition-opacity
							{!enabledParts[i] ? 'opacity-40' : ''}"
                    >
                        {#if partNumbers.length > 1}
                            <div class="flex items-center justify-between">
                                <p class="text-sm font-medium text-th-text">
                                    Part {part}
                                </p>
                                <label
                                    class="flex items-center gap-1.5 cursor-pointer select-none"
                                >
                                    <input
                                        type="checkbox"
                                        bind:checked={enabledParts[i]}
                                        class="accent-sakura-400 w-3.5 h-3.5 cursor-pointer"
                                    />
                                    <span class="text-xs text-th-text-dim"
                                        >Include</span
                                    >
                                </label>
                            </div>
                        {/if}

{#if !streamsAreUniform || showPerPart}
                            {#if streamsPerPart[i].length > 0}
                                <div>
                                    <label
                                        for="quality-{i}"
                                        class="text-xs text-th-text-dim block mb-1"
                                        >Quality</label
                                    >
                                    <select
                                        id="quality-{i}"
                                        class="w-full bg-th-input-nested border border-th-border-input rounded-lg px-2 py-1.5
									text-sm text-th-text focus:outline-none focus:ring-2 focus:ring-th-border-strong"
                                        onchange={(e) => {
                                            const idx = parseInt(
                                                (e.target as HTMLSelectElement)
                                                    .value,
                                            );
                                            const updated = [...selectedPerPart];
                                            updated[i] = streamsPerPart[i][idx];
                                            selectedPerPart = updated;
                                        }}
                                    >
                                        {#each streamsPerPart[i] as variant, vi}
                                            <option
                                                value={vi}
                                                selected={vi ===
                                                    selectedIndexPerPart[i]}
                                            >
                                                {formatBandwidth(
                                                    variant.bandwidth,
                                                )}
                                            </option>
                                        {/each}
                                    </select>
                                    {#if selectedPerPart[i]?.uri}
                                        <div class="flex justify-end mt-1">
                                            <button
                                                onclick={() => copyUrl(i)}
                                                class="text-xs text-th-text-dim hover:text-th-text-muted transition-colors"
                                            >
                                                {copiedPerPart[i]
                                                    ? "Copied!"
                                                    : "Copy URL"}
                                            </button>
                                        </div>
                                    {/if}
                                </div>
                            {:else}
                                <p
                                    class="text-xs text-amber-600 dark:text-amber-400"
                                >
                                    No stream variants found for this part.
                                </p>
                            {/if}
                        {/if}

                        <div>
                            <p class="text-xs text-th-text-dim block mb-1">Output filename</p>
                            <p class="text-sm text-th-text font-mono break-all">
                                {filenamesPerPart[i]}.mp4
                            </p>
                            {#if filenameErrors[i]}
                                <p class="text-xs text-red-400 mt-1">
                                    {filenameErrors[i]}
                                </p>
                            {:else if fileExistsPerPart[i]}
                                <p class="text-xs text-amber-600 dark:text-amber-400 mt-1">
                                    A file with this name already exists and will be overwritten.
                                </p>
                            {/if}
                        </div>
                    </div>
                {/each}
            {/if}

            {#if submitError}
                <p class="text-red-400 text-sm">{submitError}</p>
            {/if}
        </div>

        <!-- Footer -->
        <div class="p-4 border-t border-th-border flex gap-3">
            <button
                onclick={onClose}
                class="flex-1 bg-th-input hover:bg-th-input-nested text-th-text-muted text-sm font-medium
					py-2 px-4 rounded-lg transition-colors"
            >
                Cancel
            </button>
            <button
                onclick={handleSubmit}
                disabled={!canSubmit}
                class="flex-1 bg-th-accent hover:bg-th-accent-hover disabled:opacity-50
					disabled:cursor-not-allowed text-th-accent-text text-sm font-medium py-2 px-4
					rounded-lg transition-colors"
            >
                {#if submitting}
                    Starting…
                {:else if partNumbers.length === 1}
                    Download
                {:else if enabledCount === partNumbers.length}
                    Download all {partNumbers.length} parts
                {:else}
                    Download {enabledCount} of {partNumbers.length} parts
                {/if}
            </button>
        </div>
    </div>
</div>
