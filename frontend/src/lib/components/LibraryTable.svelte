<script lang="ts">
import type { LibraryItem } from '$lib/types';

export type ColumnId =
    | 'image'
    | 'content_id'
    | 'title'
    | 'content_type'
    | 'purchase_date'
    | 'downloaded_parts'
    | 'expire'
    | 'links'
    | 'download';

export interface ColumnDef {
    id: ColumnId;
    label: string;
    visible: boolean;
}

type SortField = 'title' | 'purchase_date' | 'parts' | 'expire' | 'content_id';

interface Props {
    items: LibraryItem[];
    columns: ColumnDef[];
    javstashEnabled: boolean;
    downloadCounts: Record<string, number>;
    activeDownloadCounts: Record<string, number>;
    sortField: SortField;
    sortAsc: boolean;
    onSort: (field: SortField) => void;
    onDownload?: (item: LibraryItem) => void;
    onDelete?: (item: LibraryItem) => void;
    expired?: boolean;
}

let {
    items,
    columns,
    javstashEnabled,
    downloadCounts,
    activeDownloadCounts,
    sortField,
    sortAsc,
    onSort,
    onDownload,
    onDelete,
    expired = false,
}: Props = $props();

const SORTABLE: Partial<Record<ColumnId, SortField>> = {
    content_id: 'content_id',
    title: 'title',
    purchase_date: 'purchase_date',
    downloaded_parts: 'parts',
    expire: 'expire',
};

const visibleColumns = $derived(columns.filter((c) => c.visible));

function daysLeft(expireStr: string): number {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const expire = new Date(`${expireStr}T00:00:00`);
    return Math.round((expire.getTime() - today.getTime()) / 86_400_000);
}

function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
}

let imgErrors = $state(new Set<number>());
</script>

<div class="overflow-x-auto rounded-xl border border-th-border">
    <table class="w-full text-sm">
        <thead>
            <tr class="border-b border-th-border bg-th-input/50">
                {#each visibleColumns as col (col.id)}
                    {@const sf = SORTABLE[col.id]}
                    <th
                        class="px-3 py-2 text-left text-xs font-medium text-th-text-dim whitespace-nowrap
                            {sf ? 'cursor-pointer select-none hover:text-th-text' : ''}"
                        onclick={sf ? () => onSort(sf) : undefined}
                    >
                        <span class="flex items-center gap-1">
                            {col.label}
                            {#if sf}
                                <span class="text-[10px] {sortField === sf ? 'text-th-text' : 'text-th-text-faint'}">
                                    {sortField === sf ? (sortAsc ? '↑' : '↓') : '↕'}
                                </span>
                            {/if}
                        </span>
                    </th>
                {/each}
            </tr>
        </thead>
        <tbody>
            {#each items as item (item.mylibrary_id)}
                {@const days = daysLeft(item.expire)}
                {@const downloaded = downloadCounts[item.content_id] ?? 0}
                {@const active = activeDownloadCounts[item.content_id] ?? 0}
                <tr class="border-b border-th-border last:border-0 hover:bg-th-input/30 transition-colors
                    {expired ? 'opacity-60 grayscale' : ''}">
                    {#each visibleColumns as col (col.id)}
                        <td class="px-3 py-1.5 align-middle">
                            {#if col.id === 'image'}
                                {#if imgErrors.has(item.mylibrary_id)}
                                    <div class="flex items-center justify-center bg-th-input rounded" style="height:56px;width:42px">
                                        <svg class="w-5 h-5 text-th-text-faint" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5"
                                                d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M3 8a2 2 0 012-2h10a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z" />
                                        </svg>
                                    </div>
                                {:else}
                                    <img
                                        src={item.package_image_url}
                                        alt={item.title}
                                        style="height:56px;width:auto"
                                        class="rounded object-cover"
                                        onerror={() => { imgErrors = new Set([...imgErrors, item.mylibrary_id]); }}
                                    />
                                {/if}
                            {:else if col.id === 'content_id'}
                                <span class="font-mono text-xs text-th-text-muted">{item.content_id}</span>
                            {:else if col.id === 'title'}
                                <span class="line-clamp-2 max-w-xs text-th-text leading-snug">{item.title}</span>
                            {:else if col.id === 'content_type'}
                                <span class="text-xs text-th-text-muted">{item.content_type === 'vr' ? 'VR' : 'Video'}</span>
                            {:else if col.id === 'purchase_date'}
                                <span class="text-xs text-th-text-dim whitespace-nowrap">{formatDate(item.purchase_date)}</span>
                            {:else if col.id === 'downloaded_parts'}
                                {#if !expired}
                                    <span class="text-xs text-th-text-dim whitespace-nowrap">
                                        {downloaded}/{item.parts || 1}
                                        {#if active > 0}
                                            <span class="ml-1 text-sakura-400 animate-pulse">{active} dl</span>
                                        {/if}
                                    </span>
                                {:else}
                                    <span class="text-xs text-th-text-faint">—</span>
                                {/if}
                            {:else if col.id === 'expire'}
                                <span class="text-xs whitespace-nowrap {days <= 1 ? 'text-amber-400 font-semibold' : 'text-th-text-dim'}">
                                    {#if days < 0}
                                        Expired
                                    {:else if days === 0}
                                        Today
                                    {:else if days === 1}
                                        Tomorrow
                                    {:else}
                                        {days}d left
                                    {/if}
                                </span>
                            {:else if col.id === 'links'}
                                <span class="flex items-center gap-2 whitespace-nowrap">
                                    <a
                                        href="https://r18.dev/videos/vod/movies/detail/-/id={item.content_id}/"
                                        target="_blank"
                                        rel="noopener noreferrer"
                                        class="text-xs font-semibold text-red-500 hover:text-red-400 transition-colors"
                                    >R18</a>
                                    {#if javstashEnabled && item.javstash_id}
                                        <a
                                            href="https://javstash.org/scenes/{item.javstash_id}"
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            class="text-xs font-semibold text-sakura-400 hover:text-sakura-300 transition-colors"
                                        >JS</a>
                                    {/if}
                                </span>
                            {:else if col.id === 'download'}
                                {#if !expired}
                                    <button
                                        onclick={() => onDownload?.(item)}
                                        disabled={item.trans_type === 'stream'}
                                        class="text-xs font-medium px-3 py-1 rounded-lg bg-th-accent hover:bg-th-accent-hover
                                            text-white transition-colors whitespace-nowrap disabled:opacity-40 disabled:cursor-not-allowed"
                                    >Download</button>
                                {:else}
                                    <button
                                        onclick={() => onDelete?.(item)}
                                        class="text-xs font-medium px-3 py-1 rounded-lg bg-th-input hover:border-red-800
                                            hover:text-red-400 border border-th-border text-th-text-dim transition-colors whitespace-nowrap"
                                    >Remove</button>
                                {/if}
                            {/if}
                        </td>
                    {/each}
                </tr>
            {/each}
        </tbody>
    </table>
</div>
