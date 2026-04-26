import { initLanguageDetection } from './i18n.js';

document.addEventListener('DOMContentLoaded', async () => {
    initLanguageDetection();
    
    const sidebarFooter = document.querySelector('.sidebar-footer');
    const AUTH_API = `http://${window.location.hostname}:5075/api/auth`;

    let ultraUnlocked = localStorage.getItem('ultraDarkUnlocked') === 'true';

    // Theme Toggle Logic
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

    const themeCheckbox = document.getElementById('theme-checkbox');
    let toggleCount = 0;
    let toggleTimer = null;

    if (themeCheckbox) {
        themeCheckbox.addEventListener('change', (e) => {
            const isLight = e.target.checked;
            document.body.classList.remove('light-theme', 'ultra-dark-theme');
            
            // Easter Egg Logic
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
    let currentUser = null;
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
                ${!currentUser.isVerified ? `
                    <div style="margin-top: 0.5rem;">
                        <button id="sidebar-verify-btn" class="btn btn-primary" style="padding: 0.25rem 0.5rem; font-size: 0.75rem; width: auto; background-color: var(--warning-color); border-color: var(--warning-color);">Verify Email</button>
                    </div>
                ` : ''}
            </div>
            <button id="logout-btn" class="btn btn-outline" style="width: 100%; margin-bottom: 1rem;">Logout</button>
            <div style="padding: 0 1rem 1rem 1rem; color: var(--text-secondary); font-size: 0.7rem; text-align: center; border-top: 1px solid var(--border-color); padding-top: 1rem;">
                © ${new Date().getFullYear()} BuildMeAPC.<br>
                All rights reserved.
            </div>
        `;

        const verifyBtn = document.getElementById('sidebar-verify-btn');
        if (verifyBtn) {
            verifyBtn.onclick = async () => {
                // Auto-trigger a resend so they have a fresh code when page opens
                try {
                    await fetch(`http://${window.location.hostname}:5075/api/auth/resend-verification`, {
                        method: 'POST',
                        credentials: 'include'
                    });
                } catch(e) {}
                window.location.href = 'verify.html';
            };
        }

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

    // Global Footer Injection (Contact Info)
    const mainArea = document.querySelector('.main-content'); // Use .main-content as the parent for absolute positioning
    if (mainArea) {
        mainArea.style.position = 'relative';
        mainArea.style.minHeight = '100vh';
        mainArea.style.display = 'flex';
        mainArea.style.flexDirection = 'column';

        const globalFooter = document.createElement('footer');
        globalFooter.style.marginTop = 'auto'; // Pushes footer to bottom of flex container
        globalFooter.style.padding = '1rem 0'; // Reduced padding
        globalFooter.style.borderTop = '1px solid var(--border-color)';
        globalFooter.style.color = 'var(--text-secondary)';
        globalFooter.style.fontSize = '0.8rem'; // Slightly smaller font
        globalFooter.style.textAlign = 'center';
        globalFooter.style.width = '100%';
        
        globalFooter.innerHTML = `
            <div style="display: flex; justify-content: center; gap: 2rem; flex-wrap: wrap;">
                <div>
                    <strong data-i18n="Phone">Phone</strong>: 
                    <a href="tel:0879110960" style="color: var(--accent-color); text-decoration: none;">0879110960</a>
                </div>
                <div>
                    <strong data-i18n="Email">Email</strong>: 
                    <a href="mailto:buildmeapcbulgaria@gmail.com" style="color: var(--accent-color); text-decoration: none;">buildmeapcbulgaria@gmail.com</a>
                </div>
            </div>
        `;
        mainArea.appendChild(globalFooter);
    }

    // Sidebar active state
    const currentPath = window.location.pathname.split('/').pop() || 'index.html';
    const navLinks = document.querySelectorAll('.sidebar-nav a');
    navLinks.forEach(link => {
        if (link.getAttribute('href') === currentPath) {
            link.classList.add('active');
        } else {
            link.classList.remove('active');
        }
    });

    // Learn More Button Functionality
    const learnMoreBtn = document.querySelector('a[href="#how-it-works"]');
    const moreInfoSection = document.getElementById('more-info');

    if (learnMoreBtn) {
        learnMoreBtn.addEventListener('click', (e) => {
            e.preventDefault();

            // Reveal the extra section if it exists
            if (moreInfoSection) {
                moreInfoSection.style.display = 'block';
            }

            // Smooth scroll to the section
            const target = document.querySelector('#how-it-works');
            if (target) {
                target.scrollIntoView({ behavior: 'smooth' });
            }
        });
    }

    // Generic smooth scroll for other internal anchors
    document.querySelectorAll('a[href^="#"]').forEach(anchor => {
        if (anchor === learnMoreBtn) return; // Skip the one we handled above
        anchor.addEventListener('click', function (e) {
            const href = this.getAttribute('href');
            if (href.length > 1 && href.startsWith('#')) {
                const target = document.querySelector(href);
                if (target) {
                    e.preventDefault();
                    target.scrollIntoView({ behavior: 'smooth' });
                }
            }
        });
    });
    });
