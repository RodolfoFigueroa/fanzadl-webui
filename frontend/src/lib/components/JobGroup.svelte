<script lang="ts">
import { slide } from 'svelte/transition';
import { stopJob } from '$lib/api';
import JobCard from '$lib/components/JobCard.svelte';
import type { DownloadJob } from '$lib/types';

let {
    contentId,
    jobs,
    onJobDeleted,
    onGroupStopActive,
    onGroupClearFinished,
}: {
    contentId: string;
    jobs: DownloadJob[];
    onJobDeleted: (id: string) => void;
    onGroupStopActive: (contentId: string) => void;
    onGroupClearFinished: (contentId: string) => void;
} = $props();

let collapsed = $state(true);

// ── derived counts ──────────────────────────────────────────────────────────
let running = $derived(jobs.filter((j) => j.status === 'running').length);
let pending = $derived(jobs.filter((j) => j.status === 'pending').length);
let done = $derived(jobs.filter((j) => j.status === 'done').length);
let errored = $derived(
    jobs.filter((j) => j.status === 'error' || j.status === 'cancelled').length,
);

let hasActive = $derived(running > 0 || pending > 0);
let hasFinished = $derived(done > 0 || errored > 0);

// ── aggregate progress bar ──────────────────────────────────────────────────
let avgProgress = $derived(() => {
    const pcts = jobs.map((j) => {
        if (j.status === 'done') return 100;
        if (j.status === 'pending') return 0;
        return j.percent_done ?? 0;
    });
    return pcts.reduce((a, b) => a + b, 0) / pcts.length;
});

let barColor = $derived(
    errored > 0 && running === 0 && pending === 0 && done === 0
        ? 'bg-red-500'
        : running > 0 || pending > 0
          ? 'bg-sakura-400'
          : 'bg-green-500',
);

let barAnimated = $derived(
    running > 0 &&
        jobs.some(
            (j) =>
                j.status === 'running' &&
                j.segments_done != null &&
                j.segments_total != null &&
                j.segments_total - j.segments_done <= 1,
        ),
);

// ── handlers ────────────────────────────────────────────────────────────────
function toggleCollapsed(_e: MouseEvent) {
    collapsed = !collapsed;
}

async function handleStopActive(e: MouseEvent) {
    e.stopPropagation();
    onGroupStopActive(contentId);
}

async function handleClearFinished(e: MouseEvent) {
    e.stopPropagation();
    onGroupClearFinished(contentId);
}

// ── size aggregation ─────────────────────────────────────────────────────────
function formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 ** 2) return `${(n / 1024).toFixed(2)} KB`;
    if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(2)} MB`;
    return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

let groupSizeInfo = $derived(() => {
    let downloadedBytes = 0;
    let totalBytes = 0;
    let hasSizeData = false;
    for (const j of jobs) {
        if (j.status === 'done' && j.file_size != null) {
            downloadedBytes += j.file_size;
            totalBytes += j.file_size;
            hasSizeData = true;
        } else {
            if (j.bytes_downloaded_raw != null) {
                downloadedBytes += j.bytes_downloaded_raw;
                hasSizeData = true;
            }
            if (j.bytes_total_raw != null) {
                totalBytes += j.bytes_total_raw;
                hasSizeData = true;
            }
        }
    }
    return { downloadedBytes, totalBytes, hasSizeData };
});
</script>

<div class="border border-th-border rounded-xl overflow-hidden">
    <!-- Header row -->
    <button
        onclick={toggleCollapsed}
        class="w-full flex items-center gap-2 px-4 py-3 bg-th-surface
            hover:bg-th-input transition-colors text-left"
    >
        <!-- Chevron -->
        <svg
            class="w-3.5 h-3.5 flex-shrink-0 text-th-text-dim transition-transform duration-200
                {collapsed ? '' : 'rotate-90'}"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
            viewBox="0 0 24 24"
        >
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
        </svg>

        <!-- Content ID -->
        <span class="font-mono font-medium text-sm text-th-text flex-1 min-w-0 truncate">
            {contentId}
        </span>

        <!-- Status counts -->
        <span class="hidden sm:flex items-center gap-2 text-xs flex-shrink-0">
            {#if running > 0}
                <span class="text-sakura-300">{running} downloading</span>
            {/if}
            {#if pending > 0}
                <span class="text-th-text-dim">{pending} pending</span>
            {/if}
            {#if done > 0}
                <span class="text-green-400">{done} done</span>
            {/if}
            {#if errored > 0}
                <span class="text-red-400">{errored} errored</span>
            {/if}
            {#if groupSizeInfo().hasSizeData}
                <span class="text-th-text-faint">·</span>
                {#if groupSizeInfo().totalBytes > 0}
                    <span class="text-th-text-dim tabular-nums">
                        {formatBytes(groupSizeInfo().downloadedBytes)} / {formatBytes(groupSizeInfo().totalBytes)}
                    </span>
                {:else}
                    <span class="text-th-text-dim tabular-nums">
                        {formatBytes(groupSizeInfo().downloadedBytes)}
                    </span>
                {/if}
            {/if}
        </span>

        <!-- Action buttons -->
        <span class="flex items-center gap-1.5 flex-shrink-0">
            {#if hasActive}
                <span
                    role="button"
                    tabindex="0"
                    onclick={handleStopActive}
                    onkeydown={(e) => e.key === 'Enter' && handleStopActive(e as unknown as MouseEvent)}
                    class="text-xs px-2.5 py-1 rounded-lg border border-yellow-700 text-yellow-400
                        hover:bg-yellow-900/30 transition-colors"
                >
                    Stop active
                </span>
            {/if}
            {#if hasFinished}
                <span
                    role="button"
                    tabindex="0"
                    onclick={handleClearFinished}
                    onkeydown={(e) => e.key === 'Enter' && handleClearFinished(e as unknown as MouseEvent)}
                    class="text-xs px-2.5 py-1 rounded-lg border border-th-border text-th-text-dim
                        hover:bg-gray-500/15 transition-colors"
                >
                    Clear finished
                </span>
            {/if}
        </span>
    </button>

    <!-- Mini progress bar -->
    <div class="h-1 bg-th-input w-full overflow-hidden">
        <div
            class="h-1 transition-all duration-500 {barColor} {barAnimated ? 'animate-pulse' : ''}"
            style="width: {avgProgress()}%"
        ></div>
    </div>

    <!-- Collapsible job list -->
    {#if !collapsed}
        <div transition:slide={{ duration: 180 }} class="p-3 space-y-3 bg-th-input/30">
            {#each jobs as job (job.job_id)}
                <JobCard {job} onDelete={onJobDeleted} />
            {/each}
        </div>
    {/if}
</div>
