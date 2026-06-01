<script lang="ts">
import { stopJob } from '$lib/api';
import type { DownloadJob } from '$lib/types';

let {
    job,
    onDelete,
}: { job: DownloadJob; onDelete?: (jobId: string) => void } = $props();

const statusConfig: Record<string, { label: string; classes: string }> = {
    pending: { label: 'Pending', classes: 'bg-sakura-800 text-sakura-300' },
    running: {
        label: 'Downloading',
        classes: 'bg-sakura-700/60 text-sakura-300',
    },
    done: { label: 'Complete', classes: 'bg-green-900/60 text-green-300' },
    error: { label: 'Error', classes: 'bg-red-900/60 text-red-300' },
    cancelled: {
        label: 'Stopped',
        classes: 'bg-sakura-800 text-sakura-400',
    },
};

let isMuxing = $derived(
    job.status === 'running' &&
        job.segments_done != null &&
        job.segments_total != null &&
        job.segments_total - job.segments_done <= 1,
);

let cfg = $derived(
    isMuxing
        ? { label: 'Processing…', classes: 'bg-sakura-700/40 text-sakura-200' }
        : (statusConfig[job.status] ?? statusConfig.pending),
);
let progressPct = $derived(
    job.status === 'done' ? 100 : (job.percent_done ?? 0),
);
let showProgress = $derived(job.status === 'running' || job.status === 'done');

let copied = $state(false);
let stopping = $state(false);
let deleting = $state(false);

async function handleStop() {
    stopping = true;
    try {
        await stopJob(job.job_id);
    } catch {
        stopping = false;
    }
}

async function handleDelete() {
    deleting = true;
    try {
        await stopJob(job.job_id);
        onDelete?.(job.job_id);
    } catch {
        deleting = false;
    }
}

async function copyError() {
    if (!job.error) return;
    await navigator.clipboard.writeText(job.error);
    copied = true;
    setTimeout(() => (copied = false), 2000);
}

function formatBytes(n: number): string {
    if (n < 1024) return `${n} B`;
    if (n < 1024 ** 2) return `${(n / 1024).toFixed(2)} KB`;
    if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(2)} MB`;
    return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
</script>

<div class="bg-th-surface border border-th-border rounded-xl p-4 space-y-3">
    <!-- Title row -->
    <div class="flex items-start justify-between gap-3">
        <div class="min-w-0 flex-1">
            <p class="font-medium text-th-text truncate">
                {job.output_name}.mp4
            </p>
        </div>
        <span
            class="flex-shrink-0 text-xs font-medium px-2.5 py-1 rounded-full {cfg.classes}"
        >
            {cfg.label}
        </span>
        {#if job.status === "running" || job.status === "pending"}
            <button
                onclick={handleStop}
                disabled={stopping}
                aria-label="Cancel download"
                class="flex-shrink-0 p-1 rounded text-gray-500 hover:text-red-400
                    hover:bg-red-900/30 disabled:opacity-40 transition-colors"
            >
                <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                    <rect x="6" y="6" width="12" height="12" rx="1" />
                </svg>
            </button>
        {:else if job.status === "done" || job.status === "error" || job.status === "cancelled"}
            <button
                onclick={handleDelete}
                disabled={deleting}
                aria-label="Delete download"
                class="flex-shrink-0 p-1 rounded text-gray-500 hover:text-red-400
                    hover:bg-red-900/30 disabled:opacity-40 transition-colors"
            >
                <svg
                    class="w-4 h-4"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="2"
                    viewBox="0 0 24 24"
                >
                    <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
                    />
                </svg>
            </button>
        {/if}
    </div>

    <!-- Progress bar -->
    {#if showProgress}
        <div class="space-y-1">
            <div class="w-full bg-th-input rounded-full h-1.5 overflow-hidden">
                {#if isMuxing}
                    <div class="h-1.5 rounded-full bg-sakura-400 animate-pulse w-full"></div>
                {:else}
                    <div
                        class="h-1.5 rounded-full transition-all duration-500
					{job.status === 'done' ? 'bg-green-500' : 'bg-sakura-400'}"
                        style="width: {progressPct}%"
                    ></div>
                {/if}
            </div>
            <div
                class="flex items-center justify-between text-xs text-th-text-dim"
            >
                <span>
                    {#if isMuxing}
                        Muxing…
                    {:else if job.percent_done != null}
                        {job.percent_done.toFixed(1)}%
                    {:else}
                        Starting…
                    {/if}
                </span>
                <span class="flex flex-wrap gap-x-3 gap-y-0.5">
                    {#if job.segments_done != null && job.segments_total != null && !isMuxing}
                        <span class="text-th-text-faint"
                            >{job.segments_done}/{job.segments_total} segs</span
                        >
                    {/if}
                    {#if job.bytes_downloaded != null && job.bytes_total != null && job.status === 'running' && !isMuxing}
                        <span class="text-th-text-faint"
                            >{job.bytes_downloaded} / {job.bytes_total}</span
                        >
                    {/if}
                    {#if job.speed && job.status === "running" && !isMuxing}
                        <span>{job.speed}</span>
                    {/if}
                </span>
            </div>
        </div>
    {/if}

    <!-- Error message -->
    {#if job.status === "error" && job.error}
        <div
            class="bg-red-900/20 border border-red-800 rounded-lg p-2.5 space-y-1.5"
        >
            <p class="text-xs text-red-400 font-mono break-all line-clamp-4">
                {job.error}
            </p>
            <button
                onclick={copyError}
                class="flex items-center gap-1 text-xs font-medium px-2 py-1 rounded
					bg-red-800/50 hover:bg-red-700/60 text-red-300 hover:text-white
					border border-red-700/50 transition-colors"
            >
                <svg
                    class="w-3 h-3 flex-shrink-0"
                    fill="none"
                    stroke="currentColor"
                    viewBox="0 0 24 24"
                >
                    <path
                        stroke-linecap="round"
                        stroke-linejoin="round"
                        stroke-width="2"
                        d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z"
                    />
                </svg>
                {copied ? "Copied!" : "Copy full error"}
            </button>
        </div>
    {/if}

    <!-- Output path when done -->
    {#if job.status === "done" && job.output_path}
        <p class="text-xs text-th-text-faint truncate" title={job.output_path}>
            {job.output_path}{job.file_size != null ? ` · ${formatBytes(job.file_size)}` : ''}
        </p>
    {/if}
</div>
