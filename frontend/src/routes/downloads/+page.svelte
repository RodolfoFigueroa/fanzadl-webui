<script lang="ts">
import { onDestroy, onMount } from 'svelte';
import {
    deleteJobs,
    getCachedJobs,
    getJobs,
    stopAllJobs,
    subscribeJobEvents,
} from '$lib/api';
import JobCard from '$lib/components/JobCard.svelte';
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
}

function handleJobDeleted(jobId: string) {
    const { [jobId]: _, ...rest } = jobs;
    jobs = rest;
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
		{#each sortedJobs as job (job.job_id)}
			<JobCard {job} onDelete={handleJobDeleted} />
		{/each}
	</div>
{/if}
