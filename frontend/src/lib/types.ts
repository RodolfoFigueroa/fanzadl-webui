export type JobStatus = 'pending' | 'running' | 'done' | 'error' | 'cancelled';

export interface DownloadJob {
    job_id: string;
    status: JobStatus;
    output_name: string;
    speed: string | null;
    percent_done: number | null;
    segments_done: number | null;
    segments_total: number | null;
    output_path: string | null;
    error: string | null;
}

export interface LibraryItem {
    mylibrary_id: number;
    product_id: string;
    title: string;
    content_type: 'video' | 'vr';
    package_image_url: string;
    parts: number;
    purchase_date: string;
    expire: string;
    trans_type: 'download' | 'stream';
}

export interface StreamVariant {
    index: number;
    bandwidth: number;
    resolution: string | null;
    codecs: string | null;
    uri: string;
}

export interface AppSettings {
    max_concurrent_downloads: number;
}
