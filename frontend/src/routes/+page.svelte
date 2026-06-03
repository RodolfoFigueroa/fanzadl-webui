<script lang="ts">
import { onDestroy, onMount } from 'svelte';
import { goto } from '$app/navigation';
import {
    deleteExpiredItem,
    getActiveJobCounts,
    getCachedLibrary,
    getDownloadCounts,
    getExpiredLibrary,
    getLibrary,
    getSettings,
    refreshLibrary,
    subscribeGlobalJobEvents,
    subscribeLibraryEvents,
} from '$lib/api';
import DownloadModal from '$lib/components/DownloadModal.svelte';
import ErrorAlert from '$lib/components/ErrorAlert.svelte';
import Select from '$lib/components/Select.svelte';
import TextInput from '$lib/components/TextInput.svelte';
import VideoCard from '$lib/components/VideoCard.svelte';
import type { LibraryItem } from '$lib/types';
import type { PageData } from './$types';

let { data }: { data: PageData } = $props();
const _cached = getCachedLibrary();
let library = $state<LibraryItem[]>(_cached ? Object.values(_cached) : []);
let expiredLibrary = $state<LibraryItem[]>([]);
let loading = $state(_cached === null && data.fanzaConnected !== false);
let error = $state('');
let fanzaNotConnected = $state(data.fanzaConnected === false);
let refreshing = $state(false);
let selectedItem = $state<LibraryItem | null>(null);
let javstashEnabled = $state(false);
let downloadCounts = $state<Record<string, number>>({});
let activeDownloadCounts = $state<Record<string, number>>({});

const globalJobsController = new AbortController();
const libraryController = new AbortController();
let addedDebounceTimer: ReturnType<typeof setTimeout> | null = null;

type SortField = 'title' | 'purchase_date' | 'parts' | 'expire' | 'content_id';
let sortField = $state<SortField>('purchase_date');
let sortAsc = $state(false);
let searchQuery = $state('');
let contentTypeFilter = $state<'all' | 'video' | 'vr'>('all');

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

const sortedExpiredLibrary = $derived(
    [...expiredLibrary].sort((a, b) => {
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

const _queryLower = $derived(searchQuery.trim().toLowerCase());
const _typePresent = $derived(
    contentTypeFilter === 'all' ||
        library.some((i) => i.content_type === contentTypeFilter),
);
const _typeLabel = $derived(contentTypeFilter === 'vr' ? 'VR' : 'Video');
const filteredLibrary = $derived(
    sortedLibrary.filter(
        (i) =>
            (contentTypeFilter === 'all' ||
                i.content_type === contentTypeFilter) &&
            (_queryLower === '' ||
                i.title.toLowerCase().includes(_queryLower) ||
                i.content_id.toLowerCase().includes(_queryLower)),
    ),
);
const filteredExpiredLibrary = $derived(
    sortedExpiredLibrary.filter(
        (i) =>
            (contentTypeFilter === 'all' ||
                i.content_type === contentTypeFilter) &&
            (_queryLower === '' ||
                i.title.toLowerCase().includes(_queryLower) ||
                i.content_id.toLowerCase().includes(_queryLower)),
    ),
);

async function loadLibrary() {
    error = '';
    try {
        const data = await getLibrary();
        library = Object.values(data);
        fanzaNotConnected = false;
    } catch (e) {
        if (e instanceof Error && e.message === 'fanza_not_connected') {
            fanzaNotConnected = true;
        } else {
            fanzaNotConnected = false;
            error = e instanceof Error ? e.message : 'Failed to load library';
        }
    } finally {
        loading = false;
    }
    try {
        const [expired, counts, activeCounts] = await Promise.all([
            getExpiredLibrary(),
            getDownloadCounts(),
            getActiveJobCounts(),
        ]);
        expiredLibrary = Object.values(expired);
        downloadCounts = counts;
        activeDownloadCounts = activeCounts;
    } catch {
        // expired library / counts unavailable; leave as empty
    }
}

async function handleRefresh() {
    refreshing = true;
    loading = true;
    expiredLibrary = [];
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

onMount(async () => {
    await loadLibrary();
    try {
        const s = await getSettings();
        javstashEnabled = s.javstash_enabled;
    } catch {
        // settings unavailable; leave javstashEnabled as false
    }

    subscribeGlobalJobEvents((counts) => {
        activeDownloadCounts = counts;
    }, globalJobsController.signal);

    subscribeLibraryEvents(
        (event) => {
            if (event.type === 'item_added') {
                if (addedDebounceTimer !== null)
                    clearTimeout(addedDebounceTimer);
                addedDebounceTimer = setTimeout(async () => {
                    addedDebounceTimer = null;
                    try {
                        const data = await getLibrary();
                        library = Object.values(data);
                    } catch {
                        // ignore; stale library is acceptable
                    }
                }, 300);
            } else if (
                event.type === 'item_expired' &&
                event.mylibrary_id !== null
            ) {
                const removed = library.find(
                    (i) => i.mylibrary_id === event.mylibrary_id,
                );
                library = library.filter(
                    (i) => i.mylibrary_id !== event.mylibrary_id,
                );
                if (
                    removed !== undefined &&
                    !expiredLibrary.some(
                        (i) => i.mylibrary_id === removed.mylibrary_id,
                    )
                ) {
                    expiredLibrary = [...expiredLibrary, removed];
                }
            }
            // auto_queued: activeDownloadCounts already kept live via subscribeGlobalJobEvents
        },
        undefined,
        libraryController.signal,
    );
});

onDestroy(() => {
    globalJobsController.abort();
    libraryController.abort();
    if (addedDebounceTimer !== null) clearTimeout(addedDebounceTimer);
});
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

{#if library.length > 0}
	<div class="flex items-center gap-2 mb-4 flex-wrap">
		<TextInput
			type="search"
			bind:value={searchQuery}
			placeholder="Search…"
			class="flex-1 min-w-32 max-w-xs"
		/>
		<Select
			bind:value={contentTypeFilter}
			class="min-w-[7rem]"
		>
			<option value="all">All types</option>
			<option value="video">Video</option>
			<option value="vr">VR</option>
		</Select>
		<Select
			bind:value={sortField}
			class="min-w-[9rem]"
		>
			<option value="purchase_date">Date purchased</option>
			<option value="title">Title</option>
			<option value="parts">Part count</option>
			<option value="expire">Days left</option>
			<option value="content_id">Content ID</option>
		</Select>
		<button
			onclick={() => (sortAsc = !sortAsc)}
			title={sortAsc ? "Ascending" : "Descending"}
			class="bg-th-input border border-th-border hover:border-th-border-strong text-th-text
				text-sm rounded-lg py-1.5 px-3 transition-colors select-none"
		>
			{sortAsc ? "↑" : "↓"}
		</button>
	</div>
{/if}

{#if loading}
	<div
		class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
	>
		{#each { length: 6 } as _, i}
			<div class="bg-th-surface border border-th-border rounded-xl overflow-hidden animate-pulse flex flex-col
				{i === 2 ? 'hidden sm:flex' : ''}
				{i === 3 ? 'hidden md:flex' : ''}
				{i === 4 ? 'hidden lg:flex' : ''}
				{i === 5 ? 'hidden xl:flex' : ''}
			">
				<!-- content ID + link badge -->
				<div class="px-3 pt-2 pb-2 flex items-center justify-between">
					<div class="h-5 flex items-center w-2/5">
						<div class="h-3.5 bg-th-input rounded w-full"></div>
					</div>
					<div class="h-5 flex items-center">
						<div class="h-3.5 bg-th-input rounded w-6"></div>
					</div>
				</div>
				<!-- cover image -->
				<div class="bg-th-input" style="aspect-ratio: 3/4"></div>
				<!-- info -->
				<div class="p-3 flex flex-col gap-2 flex-1">
					<!-- title: 2 lines matching text-sm leading-snug line-clamp-2 (~2.4rem) -->
					<div class="flex flex-col justify-between min-h-[2.4rem]">
						<div class="h-3.5 bg-th-input rounded w-full"></div>
						<div class="h-3.5 bg-th-input rounded w-3/4"></div>
					</div>
					<!-- date -->
					<div class="h-4 flex items-center mt-auto">
						<div class="h-3 bg-th-input rounded w-16"></div>
					</div>
					<!-- downloaded count -->
					<div class="h-4 flex items-center">
						<div class="h-3 bg-th-input rounded w-24"></div>
					</div>
					<!-- expiry -->
					<div class="h-4 flex items-center">
						<div class="h-3 bg-th-input rounded w-28"></div>
					</div>
					<!-- button -->
					<div class="h-8 bg-th-input rounded-lg mt-0.5"></div>
				</div>
			</div>
		{/each}
	</div>
{:else if fanzaNotConnected}
	<div class="flex flex-col items-center gap-3 mt-24 text-center">
		<p class="text-th-text-muted text-lg">Fanza account not connected.</p>
		<p class="text-sm text-th-text-dim">
			Go to <a href="/settings" class="text-th-text underline hover:text-th-brand transition-colors">Settings → Fanza</a> to connect your account.
		</p>
	</div>
{:else if error}
	<ErrorAlert message={error} />
{:else if library.length === 0}
	<div class="text-center text-th-text-dim mt-24">
		<p class="text-lg mb-2">Your library is empty.</p>
		<p class="text-sm">
			Click <strong>Refresh Library</strong> to fetch your titles from Fanza.
		</p>
	</div>
{:else if filteredLibrary.length === 0}
	<p class="text-th-text-dim text-sm mt-4">
		{#if !_typePresent}
			No {_typeLabel} titles in your library.
		{:else if _queryLower !== '' && contentTypeFilter !== 'all'}
			No {_typeLabel} results for &ldquo;{searchQuery.trim()}&rdquo;.
		{:else}
			No results for &ldquo;{searchQuery.trim()}&rdquo;.
		{/if}
	</p>
{:else}
	<div
		class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
	>
		{#each filteredLibrary as item (item.mylibrary_id)}
			<VideoCard {item} {javstashEnabled} downloadedCount={downloadCounts[item.content_id] ?? 0} activeDownloadCount={activeDownloadCounts[item.content_id] ?? 0} onDownload={(i) => (selectedItem = i)} />
		{/each}
	</div>
{/if}

{#if expiredLibrary.length > 0}
	<div class="mt-8 mb-4 flex items-center gap-3">
		<h2 class="text-base font-semibold text-th-text-dim">Expired</h2>
		<span class="text-xs text-th-text-faint bg-th-input rounded-full px-2 py-0.5">{expiredLibrary.length}</span>
	</div>
	<div
		class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-4"
	>
		{#each filteredExpiredLibrary as item (item.mylibrary_id)}
			<VideoCard
				{item}
				expired={true}
				{javstashEnabled}
				onDelete={async (i) => {
					try {
						await deleteExpiredItem(i.mylibrary_id);
						expiredLibrary = expiredLibrary.filter((e) => e.mylibrary_id !== i.mylibrary_id);
					} catch (e) {
						error = e instanceof Error ? e.message : 'Failed to remove expired item';
					}
				}}
			/>
		{/each}
	</div>
{/if}

{#if selectedItem}
	<DownloadModal item={selectedItem} onClose={() => (selectedItem = null)} />
{/if}
