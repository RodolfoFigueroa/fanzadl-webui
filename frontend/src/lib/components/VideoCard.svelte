<script lang="ts">
	import type { LibraryItem } from "$lib/types";

	let {
		item,
		onDownload,
	}: {
		item: LibraryItem;
		onDownload: (item: LibraryItem) => void;
	} = $props();

	let imgError = $state(false);

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString(undefined, {
			year: "numeric",
			month: "short",
			day: "numeric",
		});
	}
</script>

<div
	class="bg-th-surface border border-th-border rounded-xl overflow-hidden flex flex-col
		hover:border-th-border-strong transition-colors"
>
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
		<div
			class="text-xs text-th-text-dim flex items-center justify-between mt-auto"
		>
			<span
				>{item.parts || 1}
				{(item.parts || 1) === 1 ? "part" : "parts"}</span
			>
			<span>{formatDate(item.purchase_date)}</span>
		</div>
		<button
			onclick={() => onDownload(item)}
			class="mt-0.5 w-full bg-th-accent hover:bg-th-accent-hover text-th-accent-text text-sm
				font-medium py-1.5 px-3 rounded-lg transition-colors"
		>
			Download
		</button>
	</div>
</div>
