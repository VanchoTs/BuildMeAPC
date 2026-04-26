document.addEventListener('DOMContentLoaded', async () => {
    const AUTH_API = `http://${window.location.hostname}:5075/api/auth`;
    const ADMIN_API = `http://${window.location.hostname}:5075/api/admin`;
    const REPORTS_API = `http://${window.location.hostname}:5075/api/reports`;
    
    const tbody = document.getElementById('user-list-body');
    const reportsList = document.getElementById('reports-list');

    // Filter Inputs
    const userSearch = document.getElementById('user-search');
    const userRoleFilter = document.getElementById('user-role-filter');
    const userSort = document.getElementById('user-sort');
    const reportSearch = document.getElementById('report-search');
    const reportSort = document.getElementById('report-sort');

    // Verify session with backend
    let currentUser = null;
    try {
        const response = await fetch(`${AUTH_API}/me`, {
            credentials: 'include'
        });
        if (response.ok) {
            currentUser = await response.json();
        }
    } catch (e) {
        console.error('Session verification failed');
    }

    if (!currentUser || currentUser.role !== 'admin') {
        alert('Access Denied: Admins only.');
        window.location.href = 'index.html';
        return;
    }

    function escapeHtml(text) {
        if (!text) return '';
        const div = document.createElement('div');
        div.textContent = text.toString();
        return div.innerHTML;
    }

    const SPEC_LABELS = {
        cores: 'Cores', threads: 'Threads', baseClockGhz: 'Base Clock', boostClockGhz: 'Boost Clock', tdpW: 'TDP',
        socket: 'Socket', memoryType: 'Memory Type', vramGb: 'VRAM', memoryBusBit: 'Bus Width', boostClockMhz: 'Boost Clock',
        interface: 'Interface', formFactor: 'Form Factor', chipset: 'Chipset', ramSlots: 'RAM Slots', maxRamSpeedMhz: 'Max RAM Speed',
        maxRamAmountGb: 'Max RAM Amount', onboardWifi: 'Onboard Wi-Fi', memoryAmount: 'Capacity', memorySpeedMhz: 'Speed',
        latency: 'Latency', type: 'Type', storageSizeGb: 'Capacity', readSpeedMbps: 'Read Speed', writeSpeedMbps: 'Write Speed',
        tbwTb: 'TBW', powerW: 'Wattage', efficiency: 'Efficiency', certificate: 'Certificate', modularity: 'Modularity',
        caseSize: 'Case Size', motherboardFormFactors: 'Mobo Support', includedFans: 'Included Fans', maxCpuCoolerMm: 'Max Cooler Height',
        maxGpuLengthMm: 'Max GPU Length', maxRadiatorMm: 'Max Radiator', coolerType: 'Cooler Type', socketCompatibility: 'Socket Compatibility',
        coolerHeightMm: 'Height', fanSizeMm: 'Fan Size', fanCount: 'Fan Count', noiseDb: 'Noise Level', rpmMax: 'Max RPM'
    };

    function formatSpecValue(key, value) {
        if (value === null || value === undefined || value === '') return '';
        let displayValue = value;
        if (typeof value === 'number') displayValue = Math.round(value * 10) / 10;
        const lowKey = key.toLowerCase();
        if (lowKey.includes('clockghz')) return `${displayValue} GHz`;
        if (lowKey.includes('clockmhz') || lowKey.includes('speedmhz')) return `${displayValue} MHz`;
        if (lowKey.includes('tdpw') || key === 'powerW') return `${displayValue} W`;
        if (lowKey.includes('gb') && !lowKey.includes('amount') && key !== 'memoryAmount') return `${displayValue} GB`;
        if (lowKey.includes('mbps')) return `${displayValue} Mbps`;
        if (lowKey.includes('mm')) return `${displayValue} mm`;
        if (key === 'noiseDb') return `${displayValue} dB`;
        return displayValue.toString();
    }

    function renderComponentDetail(c) {
        const specs = Object.entries(c.specs || {})
            .filter(([_, v]) => v !== null && v !== '' && v !== undefined)
            .map(([k, v]) => {
                const label = SPEC_LABELS[k] || k;
                return `<span class="spec-pill"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(formatSpecValue(k, v))}</span>`;
            }).join('');
        const productUrl = c.url || c.Url || '#';
        return `
            <div class="component-detail-card" style="background-color: var(--surface-color); border: 1px solid var(--border-color); border-radius: 12px; padding: 1.5rem; display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem;">
                <div class="comp-info">
                    <h3 style="font-size: 0.85rem; color: var(--text-secondary); text-transform: uppercase; margin-bottom: 0.25rem;">${escapeHtml(c.type)}</h3>
                    <div class="name" style="font-size: 1.2rem; font-weight: 600;">${escapeHtml(c.brand)} ${escapeHtml(c.model)}</div>
                    <div class="comp-specs" style="font-size: 0.9rem; color: var(--text-secondary); margin-top: 0.5rem; display: flex; gap: 1rem; flex-wrap: wrap;">
                        ${specs}
                    </div>
                </div>
                <div class="comp-actions" style="display: flex; flex-direction: column; align-items: flex-end; gap: 0.5rem;">
                    <div class="comp-price" style="font-weight: bold; font-size: 1.1rem;">€${(c.price || 0).toLocaleString()}</div>
                    <a href="${productUrl}" target="_blank" class="btn btn-outline" style="font-size: 0.8rem; padding: 0.5rem 1rem;">View on pic.bg ↗</a>
                </div>
            </div>
        `;
    }

    // Tab Switching Logic
    const tabBtns = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');

    function switchTab(tabId) {
        tabBtns.forEach(b => b.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        
        const activeBtn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
        if (activeBtn) activeBtn.classList.add('active');
        
        const activeContent = document.getElementById(`${tabId}-tab`);
        if (activeContent) activeContent.classList.add('active');
    }
    
    tabBtns.forEach(btn => {
        btn.onclick = () => {
            const tabId = btn.getAttribute('data-tab');
            switchTab(tabId);
            if (tabId === 'users') loadUsers();
            if (tabId === 'reports') loadReports();
        };
    });

    // Real-time filtering listeners
    [userSearch, userRoleFilter, userSort].forEach(el => {
        el?.addEventListener('change', loadUsers);
        if (el === userSearch) el.addEventListener('input', debounce(loadUsers, 500));
    });

    [reportSearch, reportSort].forEach(el => {
        el?.addEventListener('change', loadReports);
        if (el === reportSearch) el.addEventListener('input', debounce(loadReports, 500));
    });

    loadUsers();

    async function loadUsers() {
        const search = userSearch?.value || '';
        const role = userRoleFilter?.value || 'all';
        const sort = userSort?.value || 'newest';
        
        try {
            const response = await fetch(`${ADMIN_API}/users?search=${encodeURIComponent(search)}&role=${role}&sortBy=${sort}`, {
                credentials: 'include'
            });

            if (response.ok) {
                const users = await response.json();
                renderUsers(users);
            }
        } catch (err) { console.error(err); }
    }

    function renderUsers(users) {
        if (!tbody) return;
        tbody.innerHTML = '';
        users.forEach(u => {
            const isSelf = u.email === currentUser.email;
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>${u.id}</td>
                <td>${escapeHtml(u.fullName)}</td>
                <td>${escapeHtml(u.email)} ${isSelf ? '<small>(You)</small>' : ''}</td>
                <td><span class="role-badge role-${u.role}">${u.role}</span></td>
                <td>${new Date(u.createdAt).toLocaleDateString()}</td>
                <td>
                    <select class="role-select" data-id="${u.id}" style="width: auto; padding: 0.25rem;" ${isSelf ? 'disabled' : ''}>
                        <option value="user" ${u.role === 'user' ? 'selected' : ''}>User</option>
                        <option value="writer" ${u.role === 'writer' ? 'selected' : ''}>Writer</option>
                        <option value="admin" ${u.role === 'admin' ? 'selected' : ''}>Admin</option>
                    </select>
                    ${!isSelf ? `<button class="btn btn-outline delete-user-btn" data-id="${u.id}" style="padding: 0.25rem 0.5rem; color: var(--danger-color); margin-left: 0.5rem;">Delete</button>` : ''}
                </td>
            `;
            tbody.appendChild(tr);
        });

        tbody.querySelectorAll('.role-select').forEach(sel => {
            sel.onchange = (e) => updateRole(sel.getAttribute('data-id'), e.target.value);
        });
        tbody.querySelectorAll('.delete-user-btn').forEach(btn => {
            btn.onclick = () => {
                const id = btn.getAttribute('data-id');
                if (confirm('Delete user?')) deleteUser(id);
            };
        });
    }

    async function loadReports() {
        if (!reportsList) return;
        const search = reportSearch?.value || '';
        const sort = reportSort?.value || 'newest';
        
        reportsList.innerHTML = '<p>Loading reports...</p>';
        try {
            const response = await fetch(`${REPORTS_API}?search=${encodeURIComponent(search)}&sortBy=${sort}`, {
                credentials: 'include'
            });
            if (response.ok) {
                const reports = await response.json();
                renderReports(reports);
            } else {
                reportsList.innerHTML = '<p>Failed to load reports.</p>';
            }
        } catch (err) { console.error(err); }
    }

    function renderReports(reports) {
        if (reports.length === 0) {
            reportsList.innerHTML = '<p>No reports found.</p>';
            return;
        }
        reportsList.innerHTML = '';
        reports.forEach(r => {
            const card = document.createElement('div');
            card.className = 'report-card';
            card.innerHTML = `
                <div class="report-header">
                    <span>From: <strong>${escapeHtml(r.userEmail)}</strong></span>
                    <span>${new Date(r.createdAt).toLocaleString()}</span>
                </div>
                <div class="report-comment">
                    ${r.isGibberish ? '<span class="gibberish-flag">[Likely Gibberish]</span> ' : ''}
                    "${escapeHtml(r.comment)}"
                </div>
                <div style="background-color: var(--surface-color); padding: 1rem; border-radius: 8px;">
                    <strong>Build Reported: ${escapeHtml(r.build.name)}</strong> (€${r.build.totalPrice})
                    <ul style="font-size: 0.8rem; margin-top: 0.5rem;">
                        ${r.build.components.map(c => `<li>${c.type}: ${c.brand} ${c.model}</li>`).join('')}
                    </ul>
                    <div id="expand-report-${r.id}" style="display: none; margin-top: 1rem; border-top: 1px solid var(--border-color); padding-top: 1rem;">
                        ${r.build.components.map(c => renderComponentDetail(c)).join('')}
                    </div>
                </div>
                <div class="report-actions">
                    <button class="btn btn-outline expand-report-btn" data-id="${r.id}">Expand Build</button>
                    <button class="btn btn-outline respond-report-btn" data-id="${r.id}" style="color: var(--accent-color); border-color: var(--accent-color);">Respond</button>
                    <button class="btn btn-outline delete-report-btn" data-id="${r.id}" style="color: var(--danger-color); border-color: var(--danger-color);">Delete Report</button>
                </div>
                <div id="response-form-${r.id}" style="display: none; margin-top: 1rem; background-color: var(--surface-color); padding: 1rem; border-radius: 8px;">
                    <textarea id="response-msg-${r.id}" placeholder="Type your response to the user..." style="width: 100%; min-height: 100px; margin-bottom: 0.5rem;"></textarea>
                    <div style="text-align: right;">
                        <button class="btn btn-primary send-response-btn" data-id="${r.id}">Send Email Response</button>
                    </div>
                </div>
            `;
            reportsList.appendChild(card);
        });

        reportsList.querySelectorAll('.expand-report-btn').forEach(btn => {
            btn.onclick = () => {
                const id = btn.getAttribute('data-id');
                const expandDiv = document.getElementById(`expand-report-${id}`);
                if (expandDiv.style.display === 'none') {
                    expandDiv.style.display = 'block';
                    btn.textContent = 'Collapse Build';
                } else {
                    expandDiv.style.display = 'none';
                    btn.textContent = 'Expand Build';
                }
            };
        });

        reportsList.querySelectorAll('.respond-report-btn').forEach(btn => {
            btn.onclick = () => {
                const id = btn.getAttribute('data-id');
                const form = document.getElementById(`response-form-${id}`);
                form.style.display = form.style.display === 'none' ? 'block' : 'none';
            };
        });

        reportsList.querySelectorAll('.send-response-btn').forEach(btn => {
            btn.onclick = async () => {
                const id = btn.getAttribute('data-id');
                const msg = document.getElementById(`response-msg-${id}`).value;
                if (!msg) { alert('Message is required.'); return; }

                const res = await fetch(`${REPORTS_API}/${id}/respond`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    credentials: 'include',
                    body: JSON.stringify({ message: msg })
                });

                if (res.ok) {
                    alert('Response sent successfully!');
                    document.getElementById(`response-form-${id}`).style.display = 'none';
                    document.getElementById(`response-msg-${id}`).value = '';
                } else {
                    const errorText = await res.text();
                    alert(`Failed to send response: ${errorText}`);
                }
            };
        });

        reportsList.querySelectorAll('.delete-report-btn').forEach(btn => {
            btn.onclick = async () => {
                const id = btn.getAttribute('data-id');
                if (confirm('Delete this report?')) {
                    const res = await fetch(`${REPORTS_API}/${id}`, {
                        method: 'DELETE',
                        credentials: 'include'
                    });
                    if (res.ok) loadReports();
                }
            };
        });
    }

    // Helper functions
    async function deleteUser(id) {
        const res = await fetch(`${ADMIN_API}/users/${id}`, { method: 'DELETE', credentials: 'include' });
        if (res.ok) loadUsers();
    }

    async function updateRole(id, role) {
        const res = await fetch(`${ADMIN_API}/users/${id}/role`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify(role)
        });
        if (res.ok) loadUsers();
    }

    function debounce(func, timeout = 300) {
        let timer;
        return (...args) => {
            clearTimeout(timer);
            timer = setTimeout(() => { func.apply(this, args); }, timeout);
        };
    }
});
