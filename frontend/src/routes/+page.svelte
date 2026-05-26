<script lang="ts">
import { onMount } from 'svelte';
import { goto } from '$app/navigation';
import { getCachedLibrary, getLibrary, refreshLibrary } from '$lib/api';
import DownloadModal from '$lib/components/DownloadModal.svelte';
import VideoCard from '$lib/components/VideoCard.svelte';
import type { LibraryItem } from '$lib/types';

const _cached = getCachedLibrary();
let library = $state<LibraryItem[]>(_cached ? Object.values(_cached) : []);
let loading = $state(_cached === null);
let error = $state('');
let refreshing = $state(false);
let selectedItem = $state<LibraryItem | null>(null);

type SortField = 'title' | 'purchase_date' | 'parts' | 'expire' | 'content_id';
let sortField = $state<SortField>('purchase_date');
let sortAsc = $state(false);

function daysLeft(expireStr: string): number {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const expire = new Date(`${expireStr}T00:00:00`);
    return Math.round((expire.getTime() - today.getTime()) / 86_400_000);
}

const sortedLibrary = $derived(
    [...library].sort((a, b) => {
        let cmp = 0;
        if (sortField === 'title') {
            cmp = a.title.localeCompare(b.title);
        } else if (sortField === 'purchase_date') {
            cmp =
                new Date(a.purchase_date).getTime() -
                new Date(b.purchase_date).getTime();
        } else if (sortField === 'parts') {
            cmp = (a.parts || 1) - (b.parts || 1);
        } else if (sortField === 'expire') {
            cmp = daysLeft(a.expire) - daysLeft(b.expire);
        } else if (sortField === 'content_id') {
            cmp = a.content_id.localeCompare(b.content_id);
        }
        return sortAsc ? cmp : -cmp;
    }),
);

async function loadLibrary() {
    error = '';
    try {
        const data = await getLibrary();
        library = Object.values(data);
    } catch (e) {
        error = e instanceof Error ? e.message : 'Failed to load library';
    } finally {
        loading = false;
    }
}

async function handleRefresh() {
    refreshing = true;
    loading = true;
    try {
        await refreshLibrary();
        await loadLibrary();
    } catch (e) {
        error = e instanceof Error ? e.message : 'Refresh failed';
        loading = false;
    } finally {
        refreshing = false;
    }
}

onMount(loadLibrary);
</script>

<svelte:head>
	<title>Library — FanzaDL</title>
</svelte:head>

<div class="flex items-center justify-between mb-6">
	<h1 class="text-2xl font-bold">Library</h1>
	<button
		onclick={handleRefresh}
		disabled={refreshing || loading}
		class="flex items-center gap-2 bg-th-input hover:bg-th-input-nested disabled:opacity-50
			disabled:cursor-not-allowed text-sm font-medium py-2 px-4 rounded-lg transition-colors"
	>
		<svg
			class="w-4 h-4 {refreshing ? 'animate-spin' : ''}"
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
		<span class="hidden sm:inline"
			>{refreshing ? "Refreshing…" : "Refresh Library"}</span
		>
	</button>
</div>

{#if loading}
	<div
		class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
	>
		{#each { length: 12 } as _}
			<div class="bg-th-surface rounded-xl overflow-hidden animate-pulse">
				<div class="bg-th-input" style="aspect-ratio: 16/10"></div>
				<div class="p-3 space-y-2">
					<div class="h-3 bg-th-input rounded w-3/4"></div>
					<div class="h-3 bg-th-input rounded w-1/2"></div>
					<div class="h-7 bg-th-input rounded mt-2"></div>
				</div>
			</div>
		{/each}
	</div>
{:else if error}
	<div
		class="text-red-400 bg-red-900/20 border border-red-800 rounded-lg p-4"
	>
		{error}
	</div>
{:else if library.length === 0}
	<div class="text-center text-th-text-dim mt-24">
		<p class="text-lg mb-2">Your library is empty.</p>
		<p class="text-sm">
			Click <strong>Refresh Library</strong> to fetch your titles from Fanza.
		</p>
	</div>
{:else}
	<div class="flex items-center gap-2 mb-4">
		<select
			bind:value={sortField}
			class="bg-th-input border border-th-border text-th-text text-sm rounded-lg
				py-1.5 px-3 focus:outline-none focus:border-th-border-strong"
		>
			<option value="purchase_date">Date purchased</option>
			<option value="title">Title</option>
			<option value="parts">Part count</option>
			<option value="expire">Days left</option>
			<option value="content_id">Content ID</option>
		</select>
		<button
			onclick={() => (sortAsc = !sortAsc)}
			title={sortAsc ? "Ascending" : "Descending"}
			class="bg-th-input border border-th-border hover:border-th-border-strong text-th-text
				text-sm rounded-lg py-1.5 px-3 transition-colors select-none"
		>
			{sortAsc ? "↑" : "↓"}
		</button>
	</div>
	<div
		class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
	>
		{#each sortedLibrary as item (item.mylibrary_id)}
			<VideoCard {item} onDownload={(i) => (selectedItem = i)} />
		{/each}
	</div>
{/if}

{#if selectedItem}
	<DownloadModal item={selectedItem} onClose={() => (selectedItem = null)} />
{/if}
