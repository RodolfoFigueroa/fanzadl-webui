<script lang="ts">
import { onDestroy, onMount } from 'svelte';
import {
    deleteJobs,
    getCachedJobs,
    getJobs,
    stopAllJobs,
    stopJob,
    subscribeJobEvents,
} from '$lib/api';
import JobGroup from '$lib/components/JobGroup.svelte';
import type { DownloadJob } from '$lib/types';

const _cached = getCachedJobs();
let jobs = $state<Record<string, DownloadJob>>(
    _cached ? Object.fromEntries(_cached.map((j) => [j.job_id, j])) : {},
);
let loading = $state(_cached === null);
let error = $state('');

const controllers = new Map<string, AbortController>();

function openSubscription(job: DownloadJob) {
    if (job.status === 'done' || job.status === 'error') return;
    if (controllers.has(job.job_id)) return;

    const controller = new AbortController();
    controllers.set(job.job_id, controller);

    subscribeJobEvents(
        job.job_id,
        (updated) => {
            jobs = { ...jobs, [updated.job_id]: updated };
            if (
                updated.status === 'done' ||
                updated.status === 'error' ||
                updated.status === 'cancelled'
            ) {
                controllers.get(updated.job_id)?.abort();
                controllers.delete(updated.job_id);
            }
        },
        () => {
            controllers.delete(job.job_id);
        },
        controller.signal,
    );
}

onMount(async () => {
    try {
        const existing = await getJobs();
        const map: Record<string, DownloadJob> = {};
        for (const job of existing) {
            map[job.job_id] = job;
        }
        jobs = map;
        for (const job of existing) {
            openSubscription(job);
        }
    } catch (e) {
        error = e instanceof Error ? e.message : 'Failed to load jobs';
    } finally {
        loading = false;
    }
});

onDestroy(() => {
    for (const controller of controllers.values()) {
        controller.abort();
    }
    controllers.clear();
});

let sortedJobs = $derived(Object.values(jobs));

let jobGroups = $derived(() => {
    const map = new Map<string, DownloadJob[]>();
    for (const job of Object.values(jobs)) {
        if (!job.content_id) continue;
        const existing = map.get(job.content_id);
        if (existing) {
            existing.push(job);
        } else {
            map.set(job.content_id, [job]);
        }
    }
    return map;
});

let hasFinished = $derived(
    Object.values(jobs).some((j) =>
        ['done', 'error', 'cancelled'].includes(j.status),
    ),
);
let hasDone = $derived(Object.values(jobs).some((j) => j.status === 'done'));
let hasErrored = $derived(
    Object.values(jobs).some((j) => ['error', 'cancelled'].includes(j.status)),
);
let hasActive = $derived(
    Object.values(jobs).some((j) => ['running', 'pending'].includes(j.status)),
);

async function handleStopAll() {
    await stopAllJobs();
    // Optimistic update: mark all active jobs cancelled immediately
    // so the UI reflects the correct state without waiting for SSE events
    // (SSE is still the source of truth but may lag for queued jobs).
    const updated = { ...jobs };
    for (const [id, job] of Object.entries(updated)) {
        if (job.status === 'running' || job.status === 'pending') {
            updated[id] = { ...job, status: 'cancelled' };
        }
    }
    jobs = updated;
}

function handleJobDeleted(jobId: string) {
    const { [jobId]: _, ...rest } = jobs;
    jobs = rest;
}

async function handleGroupStopActive(contentId: string) {
    const group = jobGroups().get(contentId) ?? [];
    await Promise.allSettled(
        group
            .filter((j) => j.status === 'running' || j.status === 'pending')
            .map((j) => stopJob(j.job_id)),
    );
}

async function handleGroupClearFinished(contentId: string) {
    const group = jobGroups().get(contentId) ?? [];
    const terminal = group.filter((j) =>
        ['done', 'error', 'cancelled'].includes(j.status),
    );
    await Promise.allSettled(terminal.map((j) => stopJob(j.job_id)));
    for (const j of terminal) {
        handleJobDeleted(j.job_id);
    }
}

async function handleBulkDelete(job_filter: 'finished' | 'done' | 'errored') {
    await deleteJobs(job_filter);
    const statuses =
        job_filter === 'done'
            ? ['done']
            : job_filter === 'errored'
              ? ['error', 'cancelled']
              : ['done', 'error', 'cancelled'];
    const updated = { ...jobs };
    for (const [id, job] of Object.entries(updated)) {
        if (statuses.includes(job.status)) {
            delete updated[id];
        }
    }
    jobs = updated;
}
</script>

<svelte:head>
	<title>Downloads — FanzaDL</title>
</svelte:head>

<div class="flex items-center justify-between mb-6 gap-4 flex-wrap">
	<h1 class="text-2xl font-bold">Downloads</h1>
	<div class="flex items-center gap-2 flex-wrap">
		{#if hasActive}
			<button
				onclick={handleStopAll}
				class="text-xs px-3 py-1.5 rounded-lg border border-yellow-700 text-yellow-400
				hover:bg-yellow-900/30 transition-colors"
			>
				Stop all downloads
			</button>
		{/if}
		{#if hasFinished}
			{#if hasDone}
				<button
					onclick={() => handleBulkDelete("done")}
					class="text-xs px-3 py-1.5 rounded-lg border border-green-800 text-green-400
					hover:bg-green-900/30 transition-colors"
				>
					Delete successful
				</button>
			{/if}
			{#if hasErrored}
				<button
					onclick={() => handleBulkDelete("errored")}
					class="text-xs px-3 py-1.5 rounded-lg border border-red-800 text-red-400
					hover:bg-red-900/30 transition-colors"
				>
					Delete errored/stopped
				</button>
			{/if}
			<button
				onclick={() => handleBulkDelete("finished")}
				class="text-xs px-3 py-1.5 rounded-lg border border-th-border text-th-text-dim
				hover:bg-gray-500/15 transition-colors"
			>
				Delete all finished
			</button>
		{/if}
	</div>
</div>

{#if loading}
	<div class="text-th-text-dim">Loading…</div>
{:else if error}
	<div
		class="text-red-400 bg-red-900/20 border border-red-800 rounded-lg p-4"
	>
		{error}
	</div>
{:else if sortedJobs.length === 0}
	<div class="text-center text-th-text-dim mt-24">
		<p class="text-lg mb-2">No downloads yet.</p>
		<p class="text-sm">
			Go to the <a href="/" class="text-th-link hover:underline"
				>Library</a
			> to start a download.
		</p>
	</div>
{:else}
	<div class="space-y-3 max-w-2xl">
		{#each [...jobGroups()] as [contentId, groupJobs] (contentId)}
			<JobGroup
				{contentId}
				jobs={groupJobs}
				onJobDeleted={handleJobDeleted}
				onGroupStopActive={handleGroupStopActive}
				onGroupClearFinished={handleGroupClearFinished}
			/>
		{/each}
	</div>
{/if}
