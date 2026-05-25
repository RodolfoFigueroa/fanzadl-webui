<script lang="ts">
	import { onMount, onDestroy } from "svelte";
	import { getJobs, subscribeJobEvents } from "$lib/api";
	import JobCard from "$lib/components/JobCard.svelte";
	import type { DownloadJob } from "$lib/types";

	let jobs = $state<Record<string, DownloadJob>>({});
	let loading = $state(true);
	let error = $state("");

	const controllers = new Map<string, AbortController>();

	function openSubscription(job: DownloadJob) {
		if (job.status === "done" || job.status === "error") return;
		if (controllers.has(job.job_id)) return;

		const controller = new AbortController();
		controllers.set(job.job_id, controller);

		subscribeJobEvents(
			job.job_id,
			(updated) => {
				jobs = { ...jobs, [updated.job_id]: updated };
				if (updated.status === "done" || updated.status === "error") {
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
			error = e instanceof Error ? e.message : "Failed to load jobs";
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

	const statusOrder: Record<string, number> = {
		running: 0,
		pending: 1,
		error: 2,
		done: 3,
	};

	let sortedJobs = $derived(
		Object.values(jobs).sort(
			(a, b) =>
				(statusOrder[a.status] ?? 4) - (statusOrder[b.status] ?? 4),
		),
	);
</script>

<svelte:head>
	<title>Downloads — FanzaDL</title>
</svelte:head>

<h1 class="text-2xl font-bold mb-6">Downloads</h1>

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
			<JobCard {job} />
		{/each}
	</div>
{/if}
