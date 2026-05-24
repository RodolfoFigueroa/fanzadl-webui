export type ColorTheme = 'light' | 'dark' | 'system';

const KEY = 'theme';

export function getTheme(): ColorTheme {
    return (localStorage.getItem(KEY) as ColorTheme | null) ?? 'system';
}

export function setTheme(t: ColorTheme): void {
    if (t === 'system') {
        localStorage.removeItem(KEY);
    } else {
        localStorage.setItem(KEY, t);
    }
    applyTheme(t);
}

export function applyTheme(t: ColorTheme): void {
    const html = document.documentElement;
    html.classList.remove('light', 'dark');
    if (t !== 'system') {
        html.classList.add(t);
    }
}

export function initTheme(): void {
    applyTheme(getTheme());
}
