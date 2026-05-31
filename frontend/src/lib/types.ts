export type JobStatus = 'pending' | 'running' | 'done' | 'error' | 'cancelled';

export interface DownloadJob {
    job_id: string;
    status: JobStatus;
    output_name: string;
    content_id: string | null;
    speed: string | null;
    percent_done: number | null;
    segments_done: number | null;
    segments_total: number | null;
    bytes_downloaded: string | null;
    bytes_total: string | null;
    bytes_downloaded_raw: number | null;
    bytes_total_raw: number | null;
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

export interface StreamVariant {
    index: number;
    bandwidth: number;
    codecs: string | null;
    uri?: string | null;
}

export interface AppSettings {
    max_concurrent_downloads: number;
    log_level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
    download_thread_count: number;
    javstash_enabled: boolean;
    single_part_filename_template: string;
    multi_part_filename_template: string;
    library_refresh_enabled: boolean;
    library_refresh_cron: string;
    auto_download_new_items: boolean;
    auto_download_missing_parts: boolean;
}

export interface AppSettingsPatch {
    max_concurrent_downloads?: number;
    log_level?: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR';
    download_thread_count?: number;
    javstash_api_key?: string | null;
    single_part_filename_template?: string;
    multi_part_filename_template?: string;
    library_refresh_enabled?: boolean;
    library_refresh_cron?: string;
    auto_download_new_items?: boolean;
    auto_download_missing_parts?: boolean;
}

export interface ApiKeyInfo {
    api_key: string | null;
    api_key_preview: string;
    persisted: boolean;
}

export interface LibraryEvent {
    type: 'item_added' | 'item_expired' | 'auto_queued';
    content_id: string;
    title: string | null;
    part: number | null;
    mylibrary_id: number | null;
}
