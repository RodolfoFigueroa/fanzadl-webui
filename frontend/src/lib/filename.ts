import type { LibraryItem } from './types';

export const DEFAULT_SINGLE_PART_TEMPLATE = '{content_id}';
export const DEFAULT_MULTI_PART_TEMPLATE =
    '{content_id}/{content_id}_{part:02}';

/** A fixed dummy item used for template previews on the settings page. */
export const DUMMY_LIBRARY_ITEM: LibraryItem = {
    mylibrary_id: 12345,
    content_id: 'ABC-123',
    title: 'Sample Video Title',
    content_type: 'video',
    package_image_url: '',
    parts: 3,
    purchase_date: '2024-01-15',
    expire: '2026-01-15',
    trans_type: 'download',
    javstash_id: 'abc123def456',
    javstash_studio_code: 'ABC',
};

/**
 * Applies a format spec to a resolved string value.
 * Supported string specs: U (uppercase), L (lowercase), C (capitalize first letter), T (title case).
 * Supported number specs: zero-pad notation e.g. "02" pads to 2 digits with zeros.
 */
function applySpec(value: string | number | null, spec: string): string {
    if (typeof value === 'number') {
        // Number zero-padding: spec like "02" means minimum 2 digits, zero-padded
        const match = /^0(\d+)$/.exec(spec);
        if (match) {
            return String(value).padStart(Number(match[1]), '0');
        }
        return String(value);
    }

    const str = value === null ? '' : String(value);
    switch (spec) {
        case 'U':
            return str.toUpperCase();
        case 'L':
            return str.toLowerCase();
        case 'C':
            return str.length === 0
                ? str
                : str[0].toUpperCase() + str.slice(1).toLowerCase();
        case 'T':
            return str.replace(/\b\w/g, (c) => c.toUpperCase());
        default:
            return str;
    }
}

/**
 * Sanitizes a single substituted value by stripping characters that are illegal
 * in file/path component names. Forward slashes are NOT stripped here because
 * they come from the template structure itself, not from substituted values.
 */
function sanitizeValue(value: string): string {
    // Strip characters illegal in Windows/common FS filenames within a single path component.
    // We do NOT strip `/` — that comes from the template, not the value.
    return value.replace(/[\\:*?"<>|]/g, '').trim();
}

/**
 * Renders a filename template by substituting `{field}` and `{field:spec}` tokens.
 *
 * Available fields: all properties of `LibraryItem`, plus `part` (number).
 * String specs: `:U` (uppercase), `:L` (lowercase), `:C` (capitalize), `:T` (title case).
 * Number specs: `:02`, `:03`, etc. (zero-pad to N digits).
 * Unknown field names are left as-is in the output.
 */
export function renderFilenameTemplate(
    template: string,
    item: LibraryItem,
    part: number,
): string {
    const fields: Record<string, string | number | null> = {
        ...(item as unknown as Record<string, string | number | null>),
        part,
    };

    return template.replace(
        /\{(\w+)(?::([^}]*))?\}/g,
        (_match, name: string, spec: string | undefined) => {
            if (!(name in fields)) {
                // Unknown field — leave the placeholder unchanged
                return _match;
            }
            const raw = fields[name];
            const resolved =
                spec !== undefined
                    ? applySpec(raw, spec)
                    : raw === null
                      ? ''
                      : String(raw);
            return sanitizeValue(resolved);
        },
    );
}
