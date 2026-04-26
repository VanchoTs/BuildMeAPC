const SPEC_LABELS = {
    cores: 'Cores',
    threads: 'Threads',
    baseClockGhz: 'Base Clock',
    boostClockGhz: 'Boost Clock',
    tdpW: 'TDP',
    socket: 'Socket',
    memoryType: 'Memory Type',
    vramGb: 'VRAM',
    memoryBusBit: 'Bus Width',
    boostClockMhz: 'Boost Clock',
    interface: 'Interface',
    formFactor: 'Form Factor',
    chipset: 'Chipset',
    ramSlots: 'RAM Slots',
    maxRamSpeedMhz: 'Max RAM Speed',
    maxRamAmountGb: 'Max RAM Amount',
    onboardWifi: 'Onboard Wi-Fi',
    memoryAmount: 'Capacity',
    memorySpeedMhz: 'Speed',
    latency: 'Latency',
    type: 'Type',
    storageSizeGb: 'Capacity',
    readSpeedMbps: 'Read Speed',
    writeSpeedMbps: 'Write Speed',
    tbwTb: 'TBW',
    powerW: 'Wattage',
    efficiency: 'Efficiency',
    certificate: 'Certificate',
    modularity: 'Modularity',
    caseSize: 'Case Size',
    motherboardFormFactors: 'Mobo Support',
    includedFans: 'Included Fans',
    maxCpuCoolerMm: 'Max Cooler Height',
    maxGpuLengthMm: 'Max GPU Length',
    maxRadiatorMm: 'Max Radiator',
    coolerType: 'Cooler Type',
    socketCompatibility: 'Socket Compatibility',
    coolerHeightMm: 'Height',
    fanSizeMm: 'Fan Size',
    fanCount: 'Fan Count',
    noiseDb: 'Noise Level',
    rpmMax: 'Max RPM'
};

function escapeHtml(text) {
    if (text === undefined || text === null) return '';
    const div = document.createElement('div');
    div.textContent = text.toString();
    return div.innerHTML;
}

function formatSpecValue(key, value) {
    if (value === null || value === undefined || value === '') return '';
    
    let displayValue = value;
    if (typeof value === 'number') {
        displayValue = Math.round(value * 10) / 10;
    }

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

function getCoreSpecs(build) {
    const cpu = build.components.find(c => c.type === 'CPU');
    const gpu = build.components.find(c => c.type === 'GPU');
    const ram = build.components.find(c => c.type === 'RAM');
    const ssd = build.components.find(c => c.type === 'SSD');
    const psu = build.components.find(c => c.type === 'PSU');

    const specs = [];
    if (cpu && cpu.specs) specs.push(`${cpu.specs.cores} Cores`);
    if (gpu && gpu.specs) specs.push(`${gpu.specs.vramGb}GB VRAM`);
    if (ram && ram.specs) specs.push(`${ram.specs.memoryAmount}`);
    if (ssd && ssd.specs) specs.push(`${ssd.specs.storageSizeGb}GB SSD`);
    if (psu && psu.specs) specs.push(`${psu.specs.powerW}W`);

    return specs.join(' • ');
}

function renderComponentDetail(c) {
    const specs = Object.entries(c.specs || {})
        .filter(([_, v]) => v !== null && v !== '' && v !== undefined)
        .map(([k, v]) => {
            const label = SPEC_LABELS[k] || k;
            const formattedValue = formatSpecValue(k, v);
            return `<span class="spec-pill"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(formattedValue)}</span>`;
        })
        .join('');

    const productUrl = c.url || c.Url || '#';

    return `
        <div class="component-detail-card">
            <div class="comp-info">
                <h3>${escapeHtml(c.type)}</h3>
                <div class="name">${escapeHtml(c.brand)} ${escapeHtml(c.model)}</div>
                <div class="comp-specs">
                    ${specs}
                </div>
            </div>
            <div class="comp-actions">
                <div class="comp-price">€${(c.price || 0).toLocaleString()}</div>
                <a href="${productUrl}" target="_blank" class="btn btn-outline" style="font-size: 0.8rem; padding: 0.5rem 1rem;">
                    View on pic.bg ↗
                </a>
            </div>
        </div>
    `;
}

async function reportBuild(buildData, comment) {
    const userJson = localStorage.getItem('user');
    if (!userJson) {
        alert('Please login to report build issues.');
        return;
    }

    try {
        const response = await fetch(`http://${window.location.hostname}:5075/api/reports`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({ buildData, comment })
        });

        if (response.ok) {
            const result = await response.json();
            if (result.isGibberish) {
                alert('Report received, but our filters detected your comment might not be meaningful. An admin will still review it.');
            } else {
                alert('Thank you! Your report has been submitted for review.');
            }
        } else {
            const errorText = await response.text();
            alert(`Failed to submit report: ${errorText}`);
        }
    } catch (err) {
        console.error(err);
        alert('Error connecting to the server.');
    }
}

async function loadBuilds(mylistContainer, mylistView, singleBuildView) {
    try {
        const response = await fetch(`http://${window.location.hostname}:5075/api/builds`, {
            credentials: 'include'
        });
        if (response.ok) {
            const savedBuilds = await response.json();
            if (savedBuilds.length === 0) {
                mylistContainer.innerHTML = '<div style="grid-column: 1/-1; text-align: center;"><p><a href="questionnaire.html" style="color: var(--accent-color);">You have no saved builds yet. Go to Build Now to create one!</a></p></div>';
            } else {
                renderSavedBuilds(mylistContainer, savedBuilds, mylistView, singleBuildView);
            }
        } else {
            mylistContainer.innerHTML = '<div style="grid-column: 1/-1; text-align: center;"><p>Failed to load builds.</p></div>';
        }
    } catch (e) {
        console.error(e);
        mylistContainer.innerHTML = '<div style="grid-column: 1/-1; text-align: center;"><p>Could not connect to the server.</p></div>';
    }
}

function renderSavedBuilds(container, builds, mylistView, singleBuildView) {
    container.innerHTML = '';

    // Add multi-compare button to the header area if not already there
    let headerActions = document.getElementById('mylist-header-actions');
    if (!headerActions) {
        headerActions = document.createElement('div');
        headerActions.id = 'mylist-header-actions';
        headerActions.style.textAlign = 'right';
        headerActions.style.marginBottom = '1rem';
        headerActions.innerHTML = `<button id="compare-selected-btn" class="btn btn-outline" style="display: none;">Compare Selected (0)</button>`;
        container.parentNode.insertBefore(headerActions, container);
    }

    builds.forEach((item, index) => {
        const build = item.buildData;
        const card = document.createElement('article');
        card.className = 'card build-card';
        card.id = `build-card-${index}`;
        card.style.position = 'relative';
        card.innerHTML = `
            <div style="position: absolute; top: 1rem; right: 1rem; z-index: 10;">
                <input type="checkbox" class="build-select-checkbox" data-index="${index}" style="width: 20px; height: 20px; cursor: pointer;" aria-label="Select build for comparison">
            </div>
            <h3>${escapeHtml(build.name)}</h3>
            <p style="margin-bottom: 0.5rem;">${escapeHtml(build.description)}</p>
            <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">${escapeHtml(getCoreSpecs(build))}</p>
            
            <div class="price-tag">€${build.totalPrice.toLocaleString()}</div>
            
            <ul class="component-list" aria-label="Component summary">
                ${build.components.slice(0, 4).map((c) => `
                    <li>
                        <span class="component-type">${escapeHtml(c.type)}</span>
                        <span>${escapeHtml(c.brand)} ${escapeHtml(c.model)}</span>
                    </li>
                `).join('')}
                <li style="border-bottom: none; color: var(--accent-color); font-style: italic;">+ ${build.components.length - 4} more components</li>
            </ul>
            
            <div style="margin-top: 1.5rem; display: flex; gap: 1rem; flex-wrap: wrap;">
                <button class="btn btn-outline view-details-btn" data-index="${index}" style="flex: 1;">View Details</button>
                <button class="btn btn-outline delete-build-btn" data-id="${item.id || item.Id}" style="flex: 1; border-color: var(--danger-color); color: var(--danger-color);">Remove</button>
                <button class="btn btn-primary pdf-btn" data-index="${index}" style="flex: 1;">Download PDF</button>
                <button class="btn btn-outline report-btn" data-id="${item.id || item.Id}" style="flex: 1; border-color: var(--warning-color); color: var(--warning-color);">Report</button>
            </div>
        `;
        container.appendChild(card);
    });

    const compareBtn = document.getElementById('compare-selected-btn');
    const checkboxes = container.querySelectorAll('.build-select-checkbox');
    
    checkboxes.forEach(cb => {
        cb.addEventListener('change', () => {
            const checkedCount = container.querySelectorAll('.build-select-checkbox:checked').length;
            if (compareBtn) {
                compareBtn.style.display = checkedCount >= 2 ? 'inline-block' : 'none';
                compareBtn.textContent = `Compare Selected (${checkedCount})`;
            }
        });
    });

    if (compareBtn) {
        compareBtn.onclick = () => {
            const selectedBuilds = [];
            container.querySelectorAll('.build-select-checkbox:checked').forEach(cb => {
                const idx = cb.getAttribute('data-index');
                selectedBuilds.push(builds[idx].buildData);
            });
            localStorage.setItem('generatedBuilds', JSON.stringify(selectedBuilds));
            window.location.href = 'compare.html';
        };
    }

    container.querySelectorAll('.view-details-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const index = parseInt(e.target.getAttribute('data-index') || '0', 10);
            showSingleBuild(builds[index], index, mylistView, singleBuildView, container);
        });
    });

    container.querySelectorAll('.pdf-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const index = parseInt(e.target.getAttribute('data-index') || '0', 10);
            downloadPDF(builds[index].buildData);
        });
    });

    container.querySelectorAll('.delete-build-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            if (confirm('Remove this build from your list?')) {
                try {
                    const response = await fetch(`http://${window.location.hostname}:5075/api/builds/${id}`, {
                        method: 'DELETE',
                        credentials: 'include'
                    });
                    if (response.ok) {
                        loadBuilds(container, mylistView, singleBuildView);
                    } else {
                        alert('Failed to delete build.');
                    }
                } catch (e) {
                    alert('Error connecting to the server.');
                }
            }
        });
    });

    container.querySelectorAll('.report-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = e.currentTarget.getAttribute('data-id');
            const item = builds.find(b => (b.id || b.Id) == id);
            const comment = prompt('Describe the issue with this build:');
            if (comment && item) reportBuild(item.buildData, comment);
        });
    });
}

function showSingleBuild(item, index, mylistView, singleBuildView, container) {
    const build = item.buildData;
    const content = document.getElementById('single-build-content');
    if (!content) return;

    content.innerHTML = `
        <header class="single-build-header">
            <h1>${escapeHtml(build.name)}</h1>
            <p>${escapeHtml(build.description)}</p>
            <div class="price">Total: €${build.totalPrice.toLocaleString()}</div>
        </header>

        <section class="score-cards" aria-label="Performance Scores">
            <div class="score-card">
                <span class="score-value">${build.scores ? build.scores.gaming : 0}</span>
                <span class="score-label">Gaming</span>
            </div>
            <div class="score-card">
                <span class="score-value">${build.scores ? build.scores.workstation : 0}</span>
                <span class="score-label">Workstation</span>
            </div>
            <div class="score-card">
                <span class="score-value">${build.scores ? build.scores.value : 0}</span>
                <span class="score-label">Value</span>
            </div>
        </section>

        <section class="component-detail-grid" aria-label="Detailed Component List" id="single-build-details-content">
            ${build.components.map((c) => renderComponentDetail(c)).join('')}
        </section>

        <div style="margin-top: 3rem; text-align: center; display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap;">
            <button class="btn btn-outline delete-build-btn-single" data-id="${item.id || item.Id}" style="padding: 0.75rem 2rem; border-color: var(--danger-color); color: var(--danger-color);">Remove</button>
            <button class="btn btn-primary pdf-btn-single" style="padding: 0.75rem 2rem;">Download PDF</button>
            <button class="btn btn-outline report-btn-single" style="padding: 0.75rem 2rem; border-color: var(--warning-color); color: var(--warning-color);">Report Issue</button>
        </div>
    `;

    content.querySelector('.delete-build-btn-single').addEventListener('click', async (e) => {
        const id = e.currentTarget.getAttribute('data-id');
        if (confirm('Remove this build from your list?')) {
            try {
                const response = await fetch(`http://${window.location.hostname}:5075/api/builds/${id}`, {
                    method: 'DELETE',
                    credentials: 'include'
                });
                if (response.ok) {
                    singleBuildView.style.display = 'none';
                    mylistView.style.display = 'block';
                    loadBuilds(container, mylistView, singleBuildView);
                } else {
                    alert('Failed to delete build.');
                }
            } catch (e) {
                alert('Error connecting to the server.');
            }
        }
    });

    content.querySelector('.pdf-btn-single').addEventListener('click', () => downloadPDF(build));
    content.querySelector('.report-btn-single').addEventListener('click', () => {
        const comment = prompt('Describe the issue with this build:');
        if (comment) reportBuild(build, comment);
    });

    mylistView.style.display = 'none';
    singleBuildView.style.display = 'block';
    window.scrollTo(0, 0);
    content.querySelector('h1').focus();
}

function downloadPDF(build) {
    const docHtml = document.createElement('div');
    docHtml.style.fontFamily = 'Arial, sans-serif';
    docHtml.style.padding = '40px';
    docHtml.style.color = '#333';
    docHtml.style.backgroundColor = '#fff';

    docHtml.innerHTML = `
        <h1 style="color: #161b22; border-bottom: 2px solid #333; padding-bottom: 10px;">Build Recipe: ${build.name}</h1>
        <p><strong>Description:</strong> ${build.description}</p>
        <p><strong>Total Price:</strong> €${build.totalPrice.toLocaleString()}</p>
        
        <h2 style="margin-top: 30px;">Components</h2>
        <table style="width: 100%; border-collapse: collapse; margin-top: 10px;">
            <thead>
                <tr style="background-color: #f2f2f2;">
                    <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">Part</th>
                    <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">Product</th>
                    <th style="border: 1px solid #ddd; padding: 12px; text-align: left;">Price</th>
                </tr>
            </thead>
            <tbody>
                ${build.components.map(c => {
                    const url = c.url || c.Url || '#';
                    return `
                        <tr>
                            <td style="border: 1px solid #ddd; padding: 12px;"><strong>${c.type}</strong></td>
                            <td style="border: 1px solid #ddd; padding: 12px;">
                                <a href="${url}" target="_blank" style="color: #0366d6; text-decoration: none;">
                                    ${c.brand} ${c.model} ↗
                                </a>
                            </td>
                            <td style="border: 1px solid #ddd; padding: 12px;">€${c.price.toLocaleString()}</td>
                        </tr>
                    `;
                }).join('')}
            </tbody>
        </table>

        <h2 style="margin-top: 30px;">Performance Scores</h2>
        <div style="display: flex; gap: 20px;">
            <p><strong>Gaming:</strong> ${build.scores ? build.scores.gaming : 0}/100</p>
            <p><strong>Workstation:</strong> ${build.scores ? build.scores.workstation : 0}/100</p>
            <p><strong>Value:</strong> ${build.scores ? build.scores.value : 0}/100</p>
        </div>
        
        <p style="margin-top: 50px; font-size: 0.8rem; color: #777;">Generated by BuildMeAPC on ${new Date().toLocaleDateString()}</p>
    `;

    const opt = {
        margin:       0.5,
        filename:     `${build.name.replace(/\s+/g, '_')}_Build.pdf`,
        image:        { type: 'jpeg', quality: 0.98 },
        html2canvas:  { scale: 2 },
        jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
    };

    if (typeof html2pdf !== 'undefined') {
        html2pdf().set(opt).from(docHtml).save();
    } else {
        alert('PDF generation library not loaded.');
    }
}

document.addEventListener('DOMContentLoaded', async () => {
    const mylistView = document.getElementById('mylist-view');
    const mylistContainer = document.getElementById('mylist-container');
    const singleBuildView = document.getElementById('single-build-view');
    const backBtn = document.getElementById('back-to-results-btn');

    if (!mylistContainer || !mylistView || !singleBuildView) return;

    const userJson = localStorage.getItem('user');
    if (!userJson) {
        mylistContainer.innerHTML = '<div style="grid-column: 1/-1; text-align: center;"><p><a href="login.html" style="color: var(--accent-color);">Please Login to see your saved builds.</a></p></div>';
        return;
    }

    if (backBtn) {
        backBtn.addEventListener('click', () => {
            singleBuildView.style.display = 'none';
            mylistView.style.display = 'block';
            window.scrollTo(0, 0);
        });
    }

    await loadBuilds(mylistContainer, mylistView, singleBuildView);
});
