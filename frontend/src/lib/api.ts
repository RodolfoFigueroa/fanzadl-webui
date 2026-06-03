import { fetchEventSource } from '@microsoft/fetch-event-source';
import { goto } from '$app/navigation';
import type {
    ApiKeyInfo,
    AppSettings,
    AppSettingsPatch,
    DownloadJob,
    HistoryPage,
    LibraryEvent,
    LibraryItem,
    StreamVariant,
} from './types';

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        ...(init?.headers as Record<string, string> | undefined),
    };

    const response = await fetch(path, {
        ...init,
        headers,
        credentials: 'include',
    });

    if (!response.ok) {
        if (response.status === 401 && path !== '/api/auth/login') {
            void goto('/login');
            throw new Error('Unauthenticated');
        }
        if (response.status === 503) {
            const text = await response.text();
            let detail: string | undefined;
            try {
                const json = JSON.parse(text) as { detail?: string };
                detail =
                    typeof json.detail === 'string' ? json.detail : undefined;
            } catch {
                // ignore
            }
            throw new Error(detail ?? 'Service unavailable');
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

export async function login(password: string): Promise<void> {
    await apiFetch('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ password }),
    });
}

export async function logout(): Promise<void> {
    await apiFetch('/api/auth/logout', { method: 'POST' });
}

export async function connectFanza(
    email: string,
    password: string,
): Promise<void> {
    await apiFetch('/api/settings/fanza/connect', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
    });
}

export async function disconnect(): Promise<void> {
    await apiFetch('/api/settings/fanza/disconnect', { method: 'DELETE' });
}

export async function changeAppPassword(
    current_password: string,
    new_password: string,
): Promise<void> {
    await apiFetch('/api/settings/app-password', {
        method: 'PATCH',
        body: JSON.stringify({ current_password, new_password }),
    });
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
    await apiFetch('/api/library/refresh/', { method: 'POST' });
}

export async function getExpiredLibrary(): Promise<
    Record<string, LibraryItem>
> {
    return apiFetch<Record<string, LibraryItem>>('/api/library/expired/');
}

export async function getDownloadCounts(): Promise<Record<string, number>> {
    return apiFetch<Record<string, number>>('/api/library/download-counts/');
}

export async function deleteExpiredItem(id: number): Promise<void> {
    await apiFetch(`/api/library/expired/${id}`, { method: 'DELETE' });
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
    contentId?: string,
): Promise<{ job_id: string }> {
    return apiFetch('/api/download/', {
        method: 'POST',
        body: JSON.stringify({
            video_id: videoId,
            part,
            stream_index: streamIndex,
            output_name: outputName,
            content_id: contentId ?? null,
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
    patch: AppSettingsPatch,
): Promise<AppSettings> {
    const data = await apiFetch<AppSettings>('/api/settings/', {
        method: 'PATCH',
        body: JSON.stringify(patch),
    });
    _settingsCache = data;
    return data;
}

export async function getApiKey(): Promise<ApiKeyInfo> {
    return apiFetch<ApiKeyInfo>('/api/settings/api-key');
}

export async function rotateApiKey(): Promise<ApiKeyInfo> {
    return apiFetch<ApiKeyInfo>('/api/settings/api-key/rotate', {
        method: 'POST',
    });
}

export async function testWebhook(url: string): Promise<{
    status_code?: number;
    ok?: boolean;
    error?: string;
}> {
    return apiFetch('/api/settings/webhook/test', {
        method: 'POST',
        body: JSON.stringify({ url }),
    });
}

async function sseOnOpen(response: Response): Promise<void> {
    if (response.status === 401) {
        void goto('/login');
        throw new Error('Unauthenticated');
    }
    const contentType = response.headers.get('content-type');
    const hasEventStream =
        contentType != null &&
        /(?:^|,)\s*text\/event-stream(?:\s*(?:;|$))/.test(contentType);
    if (!hasEventStream) {
        throw new Error(
            `Expected text/event-stream, got ${contentType ?? 'none'}`,
        );
    }
}

export function subscribeLibraryEvents(
    onMessage: (event: LibraryEvent) => void,
    onError?: (err: unknown) => void,
    signal?: AbortSignal,
): void {
    void fetchEventSource('/api/notifications/library', {
        signal,
        credentials: 'include',
        onopen: sseOnOpen,
        onmessage(ev) {
            try {
                onMessage(JSON.parse(ev.data) as LibraryEvent);
            } catch {
                // ignore parse errors
            }
        },
        onerror(err) {
            if (signal?.aborted) return; // intentional abort — don't retry
            if (err instanceof TypeError) return; // network/navigation cancel — allow retry
            onError?.(err);
            throw err; // unexpected server error — stop retrying
        },
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
        credentials: 'include',
        onopen: sseOnOpen,
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
            if (err instanceof TypeError) return; // network/navigation cancel — allow retry
            onError?.(err);
            throw err; // unexpected server error — stop retrying
        },
    });
}

export async function getActiveJobCounts(): Promise<Record<string, number>> {
    return apiFetch<Record<string, number>>('/api/jobs/active-counts/');
}

export function subscribeGlobalJobEvents(
    onMessage: (counts: Record<string, number>) => void,
    signal?: AbortSignal,
): void {
    void fetchEventSource('/api/jobs/global-events', {
        signal,
        credentials: 'include',
        onopen: sseOnOpen,
        onmessage(event) {
            try {
                const counts = JSON.parse(event.data) as Record<string, number>;
                onMessage(counts);
            } catch {
                // ignore malformed events
            }
        },
        onerror(err) {
            if (signal?.aborted) return; // intentional abort — don't retry
            if (err instanceof TypeError) return; // network/navigation cancel — allow retry
            throw err; // unexpected server error — stop retrying
        },
    });
}

export function subscribeJobCreatedEvents(
    onMessage: (job: DownloadJob) => void,
    signal?: AbortSignal,
): void {
    void fetchEventSource('/api/jobs/created-events', {
        signal,
        credentials: 'include',
        onopen: sseOnOpen,
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
            if (err instanceof TypeError) return; // network/navigation cancel — allow retry
            throw err; // unexpected server error — stop retrying
        },
    });
}

export interface ToastNotification {
    message: string;
    level: string;
}

export function subscribeNotifications(
    onMessage: (notification: ToastNotification) => void,
    signal?: AbortSignal,
): void {
    void fetchEventSource('/api/notifications/errors', {
        signal,
        credentials: 'include',
        onopen: sseOnOpen,
        onmessage(event) {
            if (!event.data) return;
            try {
                const notification = JSON.parse(
                    event.data,
                ) as ToastNotification;
                onMessage(notification);
            } catch {
                // ignore malformed events
            }
        },
        onerror(err) {
            if (signal?.aborted) return; // intentional abort — don't retry
            if (err instanceof TypeError) return; // network/navigation cancel — allow retry
            throw err; // unexpected server error — stop retrying
        },
    });
}

export async function getHistory(
    status: 'all' | 'done' | 'error' = 'all',
    page = 1,
    pageSize = 50,
): Promise<HistoryPage> {
    const params = new URLSearchParams({
        status,
        page: String(page),
        page_size: String(pageSize),
    });
    return apiFetch<HistoryPage>(`/api/history/?${params}`);
}

export async function deleteHistoryItems(ids: number[]): Promise<void> {
    await apiFetch('/api/history/', {
        method: 'DELETE',
        body: JSON.stringify({ ids }),
    });
}

export async function deleteAllHistory(): Promise<void> {
    await apiFetch('/api/history/', {
        method: 'DELETE',
        body: JSON.stringify({ all: true }),
    });
}
