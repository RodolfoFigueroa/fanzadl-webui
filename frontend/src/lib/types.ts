export type JobStatus = 'pending' | 'running' | 'done' | 'error' | 'cancelled';

export interface DownloadJob {
    job_id: string;
    status: JobStatus;
    output_name: string;
    speed: string | null;
    percent_done: number | null;
    segments_done: number | null;
    segments_total: number | null;
    bytes_downloaded: string | null;
    bytes_total: string | null;
    file_size: number | null;
    output_path: string | null;
    error: string | null;
}

export interface LibraryItem {
    mylibrary_id: number;
    content_id: string;
    title: string;
    content_type: 'video' | 'vr';
    package_image_url: string;
    parts: number;
    purchase_date: string;
    expire: string;
    trans_type: 'download' | 'stream';
    javstash_id: string | null;
    javstash_studio_code: string | null;
}

export interface ExpiredLibraryItem {
    mylibrary_id: number;
    content_id: string;
    title: string;
    content_type: 'video' | 'vr';
    package_image_url: string;
    purchase_date: string;
    expire: string;
    trans_type: 'download' | 'stream';
    javstash_id: string | null;
    javstash_studio_code: string | null;
}

export interface StreamVariant {
    index: number;
    bandwidth: number;
    codecs: string | null;
    uri?: string | null;
}

export interface AppSettings {
    max_concurrent_downloads: number;
    log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
    javstash_enabled: boolean;
}
