import { fetchEventSource } from '@microsoft/fetch-event-source';
import { goto } from '$app/navigation';
import type {
    AppSettings,
    DownloadJob,
    LibraryItem,
    StreamVariant,
} from './types';

const THREAD_COUNT_KEY = 'downloadThreadCount';

export function getThreadCount(): number {
    return parseInt(localStorage.getItem(THREAD_COUNT_KEY) ?? '16', 10);
}

export function setThreadCount(n: number): void {
    localStorage.setItem(THREAD_COUNT_KEY, String(n));
}

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(init?.headers as Record<string, string> | undefined),
    };

    const response = await fetch(path, { ...init, headers });

    if (!response.ok) {
        if (response.status === 401 && path !== '/api/auth/login') {
            void goto('/login');
            throw new Error('Unauthenticated');
        }
        const text = await response.text();
        let message: string;
        try {
            const json = JSON.parse(text) as { detail?: string };
            message = typeof json.detail === 'string' ? json.detail : text;
        } catch {
            message = text;
        }
        throw new Error(message);
    }

    if (
        response.status === 204 ||
        response.headers.get('content-length') === '0'
    ) {
        return undefined as T;
    }

    return response.json() as Promise<T>;
}

export async function getAuthStatus(): Promise<{ authenticated: boolean }> {
    return apiFetch('/api/auth/status');
}

export async function login(email: string, password: string): Promise<void> {
    await apiFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    });
}

export async function logout(): Promise<void> {
    await apiFetch('/api/auth/logout', { method: 'POST' });
}

export async function getLibrary(): Promise<Record<string, LibraryItem>> {
    return apiFetch('/api/library/');
}

export async function refreshLibrary(): Promise<void> {
    await apiFetch('/api/refresh_library/', { method: 'POST' });
}

export async function getStreams(
    videoId: number,
    part?: number,
): Promise<StreamVariant[]> {
    const params = new URLSearchParams({ video_id: String(videoId) });
    if (part !== undefined) params.set('part', String(part));
    return apiFetch(`/api/streams/?${params}`);
}

export async function startDownload(
    mediaUrl: string,
    outputName: string,
    threadCount: number = getThreadCount(),
): Promise<{ job_id: string }> {
    return apiFetch('/api/download/', {
        method: 'POST',
        body: JSON.stringify({
            media_url: mediaUrl,
            output_name: outputName,
            thread_count: threadCount,
        }),
    });
}

export async function getJobs(): Promise<DownloadJob[]> {
    return apiFetch('/api/jobs/');
}

export async function stopJob(jobId: string): Promise<void> {
    await apiFetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
}

export async function deleteJobs(
    filter: 'finished' | 'done' | 'errored',
): Promise<void> {
    await apiFetch(`/api/jobs/?filter=${filter}`, { method: 'DELETE' });
}

export async function stopAllJobs(): Promise<void> {
    await apiFetch('/api/jobs/?filter=active', { method: 'DELETE' });
}

export async function getSettings(): Promise<AppSettings> {
    return apiFetch('/api/settings/');
}

export async function updateSettings(
    patch: Partial<AppSettings>,
): Promise<AppSettings> {
    return apiFetch('/api/settings/', {
        method: 'PATCH',
        body: JSON.stringify(patch),
    });
}

export function subscribeJobEvents(
    jobId: string,
    onMessage: (job: DownloadJob) => void,
    onError?: (err: unknown) => void,
    signal?: AbortSignal,
): void {
    void fetchEventSource(`/api/jobs/${jobId}/events`, {
        signal,
        onmessage(event) {
            try {
                const job = JSON.parse(event.data) as DownloadJob;
                onMessage(job);
            } catch {
                // ignore malformed events
            }
        },
        onerror(err) {
            if (signal?.aborted) return; // intentional abort — don't retry
            onError?.(err);
            throw err; // stop retrying on unexpected errors
        },
    });
}
