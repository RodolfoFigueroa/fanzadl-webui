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

let _libraryCache: Record<string, LibraryItem> | null = null;

export function getCachedLibrary(): Record<string, LibraryItem> | null {
    return _libraryCache;
}

export async function getLibrary(): Promise<Record<string, LibraryItem>> {
    const data = await apiFetch<Record<string, LibraryItem>>('/api/library/');
    _libraryCache = data;
    return data;
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

export async function checkFilename(
    name: string,
): Promise<{ file_exists: boolean }> {
    const params = new URLSearchParams({ name });
    return apiFetch(`/api/download/check-filename?${params}`);
}

export async function startDownload(
    videoId: number,
    part: number,
    streamIndex: number,
    outputName: string,
    threadCount: number = getThreadCount(),
): Promise<{ job_id: string }> {
    return apiFetch('/api/download/', {
        method: 'POST',
        body: JSON.stringify({
            video_id: videoId,
            part,
            stream_index: streamIndex,
            output_name: outputName,
            thread_count: threadCount,
        }),
    });
}

let _jobsCache: DownloadJob[] | null = null;

export function getCachedJobs(): DownloadJob[] | null {
    return _jobsCache;
}

export async function getJobs(): Promise<DownloadJob[]> {
    const data = await apiFetch<DownloadJob[]>('/api/jobs/');
    _jobsCache = data;
    return data;
}

export async function stopJob(jobId: string): Promise<void> {
    await apiFetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
}

export async function deleteJobs(
    job_filter: 'finished' | 'done' | 'errored',
): Promise<void> {
    await apiFetch(`/api/jobs/?job_filter=${job_filter}`, { method: 'DELETE' });
}

export async function stopAllJobs(): Promise<void> {
    await apiFetch('/api/jobs/?job_filter=active', { method: 'DELETE' });
}

let _settingsCache: AppSettings | null = null;

export function getCachedSettings(): AppSettings | null {
    return _settingsCache;
}

export async function getSettings(): Promise<AppSettings> {
    const data = await apiFetch<AppSettings>('/api/settings/');
    _settingsCache = data;
    return data;
}

export async function updateSettings(
    patch: Partial<AppSettings>,
): Promise<AppSettings> {
    const data = await apiFetch<AppSettings>('/api/settings/', {
        method: 'PATCH',
        body: JSON.stringify(patch),
    });
    _settingsCache = data;
    return data;
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
