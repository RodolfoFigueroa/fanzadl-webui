<script lang="ts">
import type { ExpiredLibraryItem, LibraryItem } from '$lib/types';

let {
    item,
    onDownload,
    onDelete,
    javstashEnabled = false,
}: {
    item: LibraryItem | ExpiredLibraryItem;
    onDownload?: (item: LibraryItem) => void;
    onDelete?: (item: ExpiredLibraryItem) => void;
    javstashEnabled?: boolean;
} = $props();

const expired = $derived('parts' in item === false);

let imgError = $state(false);

function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString(undefined, {
        year: 'numeric',
        month: 'short',
        day: 'numeric',
    });
}

function daysLeft(expireStr: string): number {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    const expire = new Date(`${expireStr}T00:00:00`);
    return Math.round((expire.getTime() - today.getTime()) / 86_400_000);
}

const days = $derived(daysLeft(item.expire));
</script>

<div
	class="bg-th-surface border border-th-border rounded-xl overflow-hidden flex flex-col
		hover:border-th-border-strong transition-colors
		{expired ? 'opacity-50 grayscale' : ''}"
>
	<!-- Content ID -->
	<div class="px-3 pt-2 flex items-center justify-between">
		<span class="text-sm text-th-text font-mono font-medium">{item.content_id}</span>
		<div class="flex items-center gap-2">
			{#if javstashEnabled && item.javstash_id}
				<a
					href="https://javstash.org/scenes/{item.javstash_id}"
					target="_blank"
					rel="noopener noreferrer"
					class="text-xs font-semibold text-sakura-400 hover:text-sakura-300 transition-colors"
				>JS</a>
			{/if}
			<a
				href="https://r18.dev/videos/vod/movies/detail/-/id={item.content_id}/"
				target="_blank"
				rel="noopener noreferrer"
				class="text-xs font-semibold text-red-500 hover:text-red-400 transition-colors"
			>R18</a>
		</div>
	</div>

	<!-- Cover image -->
	<div class="relative bg-th-input overflow-hidden" style="aspect-ratio: 3/4">
		{#if !imgError}
			<img
				src={item.package_image_url}
				alt={item.title}
				class="w-full h-full object-contain"
				onerror={() => (imgError = true)}
			/>
		{:else}
			<div
				class="w-full h-full flex items-center justify-center text-th-text-faint"
			>
				<svg
					class="w-12 h-12"
					fill="none"
					stroke="currentColor"
					viewBox="0 0 24 24"
				>
					<path
						stroke-linecap="round"
						stroke-linejoin="round"
						stroke-width="1.5"
						d="M15 10l4.553-2.069A1 1 0 0121 8.845v6.31a1 1 0 01-1.447.894L15 14M3 8a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z"
					/>
				</svg>
			</div>
		{/if}
		<span
			class="absolute top-2 right-2 text-xs font-medium px-2 py-0.5 rounded bg-black/60 backdrop-blur-sm
				{item.content_type === 'vr' ? 'text-sakura-300' : 'text-sakura-200'}"
		>
			{item.content_type === "vr" ? "VR" : "Video"}
		</span>
	</div>

	<!-- Info -->
	<div class="p-3 flex flex-col gap-2 flex-1">
		<h3 class="text-sm font-medium text-th-text leading-snug line-clamp-2">
			{item.title}
		</h3>
		<div class="text-xs text-th-text-dim flex items-center justify-between mt-auto">
			{#if !expired}
				<span
					>{'parts' in item ? item.parts : 1}
					{('parts' in item ? item.parts : 1) === 1 ? "part" : "parts"}</span
				>
			{:else}
				<span></span>
			{/if}
			<span>{formatDate(item.purchase_date)}</span>
		</div>
		<div
			class="text-xs flex items-center gap-1
				{days <= 1 ? 'text-amber-400 font-semibold' : 'text-th-text-dim'}"
		>
			<svg
				class="w-3 h-3 shrink-0"
				fill="none"
				stroke="currentColor"
				viewBox="0 0 24 24"
			>
				<path
					stroke-linecap="round"
					stroke-linejoin="round"
					stroke-width="2"
					d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"
				/>
			</svg>
			{#if days < 0}
				<span>Expired</span>
			{:else if days === 0}
				<span>Expires today</span>
			{:else if days === 1}
				<span>Expires tomorrow</span>
			{:else}
				<span>Expires in {days} days</span>
			{/if}
		</div>
		{#if !expired}
			<button
				onclick={() => onDownload?.(item as LibraryItem)}
				class="mt-0.5 w-full bg-th-accent hover:bg-th-accent-hover text-th-accent-text text-sm
					font-medium py-1.5 px-3 rounded-lg transition-colors"
			>
				Download
			</button>
		{:else}
			<button
				onclick={() => onDelete?.(item as ExpiredLibraryItem)}
				title="Remove from tracking"
				class="mt-0.5 w-full flex items-center justify-center gap-1.5 bg-th-input
					hover:bg-th-input-nested text-th-text-dim hover:text-red-400 text-sm
					py-1.5 px-3 rounded-lg transition-colors"
			>
				<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
					<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
						d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
				</svg>
				<span>Remove</span>
			</button>
		{/if}
	</div>
</div>
