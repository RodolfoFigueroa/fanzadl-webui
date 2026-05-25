<script lang="ts">
	import { afterNavigate, goto } from "$app/navigation";
	import { page } from "$app/state";
	import { getTheme, setTheme, initTheme } from "$lib/theme";
	import type { ColorTheme } from "$lib/theme";
	import { getAuthStatus, logout } from "$lib/api";
	import "../app.css";

	let { children } = $props();
	let theme = $state<ColorTheme>("system");

	$effect(() => {
		theme = getTheme();
		initTheme();
	});

	function selectTheme(t: ColorTheme) {
		theme = t;
		setTheme(t);
	}

	afterNavigate(async ({ to }) => {
		if (to?.url.pathname === "/login") return;
		const s = await getAuthStatus();
		if (!s.authenticated) {
			goto("/login");
		}
	});

	async function handleLogout() {
		try {
			await logout();
		} finally {
			goto("/login");
		}
	}

	const navLinks = [
		{ href: "/", label: "Library" },
		{ href: "/downloads", label: "Downloads" },
	];
</script>

<div class="min-h-screen bg-th-base text-th-text flex flex-col">
	<nav
		class="bg-th-surface border-b border-th-border px-6 py-3 flex items-center gap-6"
	>
		<span class="text-th-brand font-bold text-lg tracking-tight"
			>FanzaDL</span
		>
		{#each navLinks as link}
			<a
				href={link.href}
				class="text-sm text-th-link hover:text-th-link-hover transition-colors
					{page.url.pathname === link.href ? 'text-th-link-hover font-medium' : ''}"
			>
				{link.label}
			</a>
		{/each}
		<div class="ml-auto flex items-center gap-4">
			<div
				class="flex items-center gap-0.5 bg-th-input rounded-lg p-0.5"
				role="group"
				aria-label="Color theme"
			>
				<button
					onclick={() => selectTheme("light")}
					class="p-1.5 rounded-md transition-colors
						{theme === 'light'
						? 'bg-th-surface text-th-brand shadow-sm'
						: 'text-th-text-dim hover:text-th-text-muted'}"
					title="Light"
					aria-label="Light mode"
					aria-pressed={theme === "light"}
				>
					<svg
						class="w-3.5 h-3.5"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						viewBox="0 0 24 24"
					>
						<circle cx="12" cy="12" r="4" />
						<path
							stroke-linecap="round"
							d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"
						/>
					</svg>
				</button>
				<button
					onclick={() => selectTheme("dark")}
					class="p-1.5 rounded-md transition-colors
						{theme === 'dark'
						? 'bg-th-surface text-th-brand shadow-sm'
						: 'text-th-text-dim hover:text-th-text-muted'}"
					title="Dark"
					aria-label="Dark mode"
					aria-pressed={theme === "dark"}
				>
					<svg
						class="w-3.5 h-3.5"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						viewBox="0 0 24 24"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"
						/>
					</svg>
				</button>
				<button
					onclick={() => selectTheme("system")}
					class="p-1.5 rounded-md transition-colors
						{theme === 'system'
						? 'bg-th-surface text-th-brand shadow-sm'
						: 'text-th-text-dim hover:text-th-text-muted'}"
					title="System"
					aria-label="System theme"
					aria-pressed={theme === "system"}
				>
					<svg
						class="w-3.5 h-3.5"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						viewBox="0 0 24 24"
					>
						<path
							stroke-linecap="round"
							stroke-linejoin="round"
							d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"
						/>
					</svg>
				</button>
			</div>
			<a
				href="/settings"
				class="text-sm text-th-link hover:text-th-link-hover transition-colors
					{page.url.pathname === '/settings' ? 'text-th-link-hover font-medium' : ''}"
			>
				Settings
			</a>
			{#if page.url.pathname !== "/login"}
				<button
					onclick={handleLogout}
					class="text-sm text-th-text-dim hover:text-th-text-muted transition-colors"
				>
					Logout
				</button>
			{/if}
		</div>
	</nav>
	<main class="flex-1 p-6 max-w-screen-2xl mx-auto w-full">
		{@render children()}
	</main>
</div>
