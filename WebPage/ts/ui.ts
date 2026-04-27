import { initLanguageDetection } from './i18n.js';

document.addEventListener('DOMContentLoaded', async () => {
    initLanguageDetection();
    
    const sidebarFooter = document.querySelector('.sidebar-footer');
    const AUTH_API = `http://${window.location.hostname}:5075/api/auth`;

    let ultraUnlocked = localStorage.getItem('ultraDarkUnlocked') === 'true';

    // Theme Toggle Logic: Supports Dark (default), Light, and Ultra Dark.
    const savedTheme = localStorage.getItem('theme') || 'dark';
    if (savedTheme === 'light') {
        document.body.classList.add('light-theme');
    } else if (savedTheme === 'ultra' && ultraUnlocked) {
        document.body.classList.add('ultra-dark-theme');
    }

    const themeWrapper = document.createElement('div');
    themeWrapper.className = 'theme-switch-wrapper';
    themeWrapper.innerHTML = `
        <label class="theme-switch" for="theme-checkbox">
            <input type="checkbox" id="theme-checkbox" ${savedTheme === 'light' ? 'checked' : ''} />
            <div class="slider">
                <span class="icon moon material-symbols-outlined">dark_mode</span>
                <span class="icon sun material-symbols-outlined">light_mode</span>
            </div>
        </label>
    `;
    document.body.appendChild(themeWrapper);

    const themeCheckbox = document.getElementById('theme-checkbox') as HTMLInputElement;
    let toggleCount = 0;
    let toggleTimer: any = null;

    if (themeCheckbox) {
        themeCheckbox.addEventListener('change', (e) => {
            const isLight = (e.target as HTMLInputElement).checked;
            document.body.classList.remove('light-theme', 'ultra-dark-theme');
            
            // Easter Egg Logic: Quickly toggling the theme 6 times unlocks "Ultra Dark" mode.
            toggleCount++;
            clearTimeout(toggleTimer);
            
            if (toggleCount >= 6) {
                ultraUnlocked = !ultraUnlocked;
                localStorage.setItem('ultraDarkUnlocked', ultraUnlocked.toString());
                if (ultraUnlocked) {
                    alert('Ultra Dark Mode Unlocked! Toggling to dark will now activate Ultra Dark Mode.');
                } else {
                    alert('Ultra Dark Mode Disabled. Restored normal Dark Mode.');
                }
                toggleCount = 0;
            } else {
                toggleTimer = setTimeout(() => { toggleCount = 0; }, 800);
            }
            
            let newTheme = 'dark';
            if (isLight) {
                newTheme = 'light';
                document.body.classList.add('light-theme');
            } else if (ultraUnlocked) {
                newTheme = 'ultra';
                document.body.classList.add('ultra-dark-theme');
            }
            localStorage.setItem('theme', newTheme);
        });
    }
    
    // Verify session via API to be safe
    let currentUser: any = null;
    try {
        const response = await fetch(`${AUTH_API}/me`, { credentials: 'include' });
        if (response.ok) {
            currentUser = await response.json();
            // Update local storage just in case
            localStorage.setItem('user', JSON.stringify({
                name: currentUser.fullName,
                email: currentUser.email,
                role: currentUser.role
            }));
        } else {
            localStorage.removeItem('user');
        }
    } catch(e) {
        // Fallback to local storage if API is unreachable
        const userJson = localStorage.getItem('user');
        if (userJson) {
            try { currentUser = JSON.parse(userJson); } catch (e) {}
        }
    }

    if (currentUser && sidebarFooter) {
        // Add Admin Panel link if role is admin
        if (currentUser.role === 'admin') {
            const nav = document.querySelector('.sidebar-nav');
            // Prevent duplicate admin links
            if (nav && !nav.querySelector('a[href="admin.html"]')) {
                const adminLink = document.createElement('a');
                adminLink.href = 'admin.html';
                adminLink.innerHTML = '<span>🔐</span> Admin Panel';
                nav.appendChild(adminLink);
            }
        }

        sidebarFooter.innerHTML = `
            <div style="padding: 0.75rem 1rem; color: var(--text-secondary); font-size: 0.9rem;">
                Logged in as: <br>
                <strong style="color: var(--accent-color);">${currentUser.name || currentUser.fullName}</strong>
            </div>
            <button id="logout-btn" class="btn btn-outline" style="width: 100%;">Logout</button>
        `;

        document.getElementById('logout-btn')?.addEventListener('click', async () => {
            try {
                await fetch(`${AUTH_API}/logout`, { method: 'POST', credentials: 'include' });
            } catch(e) {}
            localStorage.removeItem('authToken');
            localStorage.removeItem('user');
            localStorage.removeItem('userName');
            window.location.href = 'index.html';
        });
    }

    // Mark active link in sidebar
    const currentPath = window.location.pathname.split('/').pop() || 'index.html';
    const navLinks = document.querySelectorAll('.sidebar-nav a');
    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });
});
