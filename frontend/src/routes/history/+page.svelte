<script lang="ts">
import { onMount } from 'svelte';
import { deleteAllHistory, deleteHistoryItems, getHistory } from '$lib/api';
import Badge from '$lib/components/Badge.svelte';
import Button from '$lib/components/Button.svelte';
import FormCheckbox from '$lib/components/FormCheckbox.svelte';
import type { HistoryItem } from '$lib/types';

type StatusFilter = 'all' | 'done' | 'error';

let filter = $state<StatusFilter>('all');
let page = $state(1);
const pageSize = 50;

let items = $state<HistoryItem[]>([]);
let total = $state(0);
let loading = $state(true);
let fetchError = $state('');

let selected = $state(new Set<number>());
let confirmingDeleteAll = $state(false);
let deleting = $state(false);
let deleteError = $state('');

let expandedErrors = $state(new Set<number>());

const totalPages = $derived(Math.max(1, Math.ceil(total / pageSize)));
const allChecked = $derived(
    items.length > 0 && items.every((item) => selected.has(item.id)),
);
const someChecked = $derived(
    items.some((item) => selected.has(item.id)) && !allChecked,
);

async function load() {
    loading = true;
    fetchError = '';
    try {
        const result = await getHistory(filter, page, pageSize);
        items = result.items;
        total = result.total;
    } catch (e) {
        fetchError = e instanceof Error ? e.message : 'Failed to load history';
    } finally {
        loading = false;
    }
}

function setFilter(f: StatusFilter) {
    filter = f;
    page = 1;
    selected = new Set();
    void load();
}

function setPage(p: number) {
    page = p;
    selected = new Set();
    void load();
}

function toggleSelect(id: number) {
    const next = new Set(selected);
    if (next.has(id)) {
        next.delete(id);
    } else {
        next.add(id);
    }
    selected = next;
}

function toggleAll() {
    if (allChecked) {
        selected = new Set();
    } else {
        selected = new Set(items.map((i) => i.id));
    }
}

async function handleDeleteSelected() {
    if (selected.size === 0) return;
    deleting = true;
    deleteError = '';
    try {
        await deleteHistoryItems([...selected]);
        selected = new Set();
        await load();
    } catch (e) {
        deleteError = e instanceof Error ? e.message : 'Delete failed';
    } finally {
        deleting = false;
    }
}

async function handleDeleteAll() {
    deleting = true;
    deleteError = '';
    confirmingDeleteAll = false;
    try {
        await deleteAllHistory();
        selected = new Set();
        page = 1;
        await load();
    } catch (e) {
        deleteError = e instanceof Error ? e.message : 'Delete failed';
    } finally {
        deleting = false;
    }
}

function toggleError(id: number) {
    const next = new Set(expandedErrors);
    if (next.has(id)) {
        next.delete(id);
    } else {
        next.add(id);
    }
    expandedErrors = next;
}

function formatBytes(bytes: number | null): string {
    if (bytes === null) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    if (bytes < 1024 * 1024 * 1024)
        return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatDate(iso: string): string {
    try {
        return new Date(iso).toLocaleString();
    } catch {
        return iso;
    }
}

onMount(() => {
    void load();
});
</script>

<svelte:head>
	<title>History — FanzaDL</title>
</svelte:head>

<div class="flex items-center justify-between mb-6 gap-4 flex-wrap">
	<h1 class="text-2xl font-bold">History</h1>

		<div class="flex items-center gap-2 flex-wrap">
		{#if deleteError}
			<span class="text-xs text-red-500">{deleteError}</span>
		{/if}

		<Button
			variant="ghost-destructive"
			size="sm"
			onclick={() => handleDeleteSelected()}
			disabled={selected.size === 0 || deleting}
		>Delete selected ({selected.size})</Button>

		{#if confirmingDeleteAll}
			<span class="text-sm text-th-text-muted">Are you sure?</span>
			<Button
				variant="destructive"
				size="sm"
				onclick={() => handleDeleteAll()}
				disabled={deleting}
			>Yes, delete all</Button>
			<Button
				variant="secondary"
				size="sm"
				onclick={() => (confirmingDeleteAll = false)}
			>Cancel</Button>
		{:else}
			<Button
				variant="ghost-destructive"
				size="sm"
				onclick={() => (confirmingDeleteAll = true)}
				disabled={deleting || total === 0}
			>Delete all</Button>
		{/if}
	</div>
</div>

<!-- Filter bar -->
<div
	class="flex items-center gap-1 bg-th-input rounded-lg p-1 w-fit mb-4"
		role="group"
		aria-label="Status filter"
	>
		{#each (['all', 'done', 'error'] as const) as f}
			<button
				onclick={() => setFilter(f)}
				class="px-3 py-1 text-sm rounded-md transition-colors capitalize
					{filter === f
					? 'bg-th-surface text-th-text shadow-sm font-medium'
					: 'text-th-text-dim hover:text-th-text'}"
				aria-pressed={filter === f}
			>
				{f}
			</button>
		{/each}
</div>

{#if fetchError}
		<p class="text-sm text-red-500">{fetchError}</p>
{:else if loading}
	<p class="text-sm text-th-text-muted">Loading…</p>
{:else if items.length === 0}
	<div class="py-16 text-center text-th-text-muted text-sm">
		No download history yet.
	</div>
{:else}
	<div class="overflow-x-auto rounded-lg border border-th-border">
			<table class="min-w-full text-sm">
				<thead class="bg-th-surface text-th-text-muted uppercase text-xs tracking-wide">
					<tr>
						<th class="px-3 py-2.5 w-8">
							<FormCheckbox
								checked={allChecked}
								indeterminate={someChecked}
								onchange={toggleAll}
								ariaLabel="Select all"
							/>
						</th>
						<th class="px-3 py-2.5 text-left">Status</th>
						<th class="px-3 py-2.5 text-left">File</th>
						<th class="px-3 py-2.5 text-left hidden sm:table-cell">Content ID</th>
						<th class="px-3 py-2.5 text-left hidden sm:table-cell">Source</th>
						<th class="px-3 py-2.5 text-right hidden sm:table-cell">Bandwidth</th>
						<th class="px-3 py-2.5 text-right">Size</th>
						<th class="px-3 py-2.5 text-left">Completed</th>
						<th class="px-3 py-2.5 text-left hidden sm:table-cell">Error</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-th-border">
					{#each items as item (item.id)}
						<tr class="hover:bg-th-surface/50 transition-colors {selected.has(item.id) ? 'bg-th-surface/30' : ''}">
							<td class="px-3 py-2">
								<FormCheckbox
									checked={selected.has(item.id)}
									onchange={() => toggleSelect(item.id)}
									ariaLabel="Select row"
								/>
							</td>
							<td class="px-3 py-2">
								{#if item.status === 'done'}
									<Badge class="bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300">
										done
									</Badge>
								{:else}
									<Badge class="bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300">
										error
									</Badge>
								{/if}
							</td>
							<td class="px-3 py-2 max-w-xs truncate text-th-text font-mono text-xs" title={item.output_name}>
								{item.output_name}
							</td>
						<td class="px-3 py-2 text-th-text-muted font-mono text-xs hidden sm:table-cell">
							{item.content_id ?? '—'}
						</td>
						<td class="px-3 py-2 hidden sm:table-cell">
								{#if item.source === 'auto'}
									<Badge class="bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300">
										auto
									</Badge>
								{:else}
									<Badge class="bg-th-input text-th-text-muted">
										manual
									</Badge>
								{/if}
							</td>
						<td class="px-3 py-2 text-right text-th-text-muted tabular-nums hidden sm:table-cell">
								{item.bandwidth_mbps !== null ? `${item.bandwidth_mbps.toFixed(1)} Mbps` : '—'}
							</td>
							<td class="px-3 py-2 text-right text-th-text-muted tabular-nums">
								{formatBytes(item.file_size)}
							</td>
							<td class="px-3 py-2 text-th-text-muted text-xs whitespace-nowrap">
								{formatDate(item.completed_at)}
							</td>
						<td class="px-3 py-2 max-w-xs hidden sm:table-cell">
								{#if item.error}
									<button
										onclick={() => toggleError(item.id)}
										class="text-left text-xs text-red-500 hover:text-red-400 transition-colors"
										title={expandedErrors.has(item.id) ? 'Collapse' : 'Expand'}
									>
										{#if expandedErrors.has(item.id)}
											<span class="whitespace-pre-wrap break-all">{item.error}</span>
										{:else}
											<span class="truncate block max-w-[200px]">{item.error}</span>
										{/if}
									</button>
								{:else}
									<span class="text-th-text-dim">—</span>
								{/if}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
	</div>

	<!-- Pagination -->
	{#if totalPages > 1}
		<div class="flex items-center justify-center gap-3 pt-2">
			<Button
				variant="secondary"
				size="sm"
				onclick={() => setPage(page - 1)}
				disabled={page <= 1}
			>Previous</Button>
			<span class="text-sm text-th-text-muted">
				Page {page} of {totalPages}
				<span class="text-th-text-dim ml-1">({total} total)</span>
			</span>
			<Button
				variant="secondary"
				size="sm"
				onclick={() => setPage(page + 1)}
				disabled={page >= totalPages}
			>Next</Button>
		</div>
	{/if}
{/if}
