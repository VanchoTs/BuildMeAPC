import { Build } from './types.js';

declare const html2pdf: any;

const SPEC_LABELS: Record<string, string> = {
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

function escapeHtml(text: any) {
    if (text === undefined || text === null) return '';
    const div = document.createElement('div');
    div.textContent = text.toString();
    return div.innerHTML;
}

function formatSpecValue(key: string, value: any): string {
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

function getCoreSpecs(build: any): string {
    const cpu = build.components.find((c: any) => c.type === 'CPU');
    const gpu = build.components.find((c: any) => c.type === 'GPU');
    const ram = build.components.find((c: any) => c.type === 'RAM');
    const ssd = build.components.find((c: any) => c.type === 'SSD');
    const psu = build.components.find((c: any) => c.type === 'PSU');

    const specs = [];
    if (cpu) specs.push(`${cpu.specs.cores} Cores`);
    if (gpu) specs.push(`${gpu.specs.vramGb}GB VRAM`);
    if (ram) specs.push(`${ram.specs.memoryAmount}`);
    if (ssd) specs.push(`${ssd.specs.storageSizeGb}GB SSD`);
    if (psu) specs.push(`${psu.specs.powerW}W`);

    return specs.join(' • ');
}

function renderComponentDetail(c: any): string {
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

    let savedBuilds: any[] = [];
    
    async function loadBuilds() {
        try {
            const response = await fetch(`http://${window.location.hostname}:5075/api/builds`, {
                credentials: 'include'
            });
            if (response.ok) {
                savedBuilds = await response.json();
                if (savedBuilds.length === 0) {
                    mylistContainer!.innerHTML = '<div style="grid-column: 1/-1; text-align: center;"><p><a href="questionnaire.html" style="color: var(--accent-color);">You have no saved builds yet. Go to Build Now to create one!</a></p></div>';
                } else {
                    renderSavedBuilds(mylistContainer!, savedBuilds);
                }
            } else {
                mylistContainer!.innerHTML = '<div style="grid-column: 1/-1; text-align: center;"><p>Failed to load builds.</p></div>';
            }
        } catch (e) {
            console.error(e);
            mylistContainer!.innerHTML = '<div style="grid-column: 1/-1; text-align: center;"><p>Could not connect to the server.</p></div>';
        }
    }

    await loadBuilds();

    if (backBtn) {
        backBtn.addEventListener('click', () => {
            singleBuildView!.style.display = 'none';
            mylistView!.style.display = 'block';
            window.scrollTo(0, 0);
        });
    }

    function renderSavedBuilds(container: HTMLElement, builds: any[]) {
        container.innerHTML = '';
        builds.forEach((item, index) => {
            const build = item.buildData;
            const card = document.createElement('article');
            card.className = 'card build-card';
            card.id = `build-card-${index}`;
            card.innerHTML = `
                <h3>${escapeHtml(build.name)}</h3>
                <p style="margin-bottom: 0.5rem;">${escapeHtml(build.description)}</p>
                <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">${escapeHtml(getCoreSpecs(build))}</p>
                
                <div class="price-tag">€${build.totalPrice.toLocaleString()}</div>
                
                <ul class="component-list" aria-label="Component summary">
                    ${build.components.slice(0, 4).map((c: any) => `
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
                </div>
            `;
            container.appendChild(card);
        });

        container.querySelectorAll('.view-details-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt((e.target as HTMLElement).getAttribute('data-index') || '0', 10);
                const item = builds[index];
                if (item) showSingleBuild(item, index);
            });
        });

        container.querySelectorAll('.pdf-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const index = parseInt((e.target as HTMLElement).getAttribute('data-index') || '0', 10);
                const card = (e.target as HTMLElement).closest('.build-card');
                downloadPDF(builds[index].buildData, card as HTMLElement);
            });
        });

        container.querySelectorAll('.delete-build-btn').forEach(btn => {
            btn.addEventListener('click', async (e) => {
                const id = (e.currentTarget as HTMLElement).getAttribute('data-id');
                if (!id || id === 'undefined') {
                    alert('Invalid build ID.');
                    return;
                }
                if (confirm('Remove this build from your list?')) {
                    try {
                        const response = await fetch(`http://${window.location.hostname}:5075/api/builds/${id}`, {
                            method: 'DELETE',
                            credentials: 'include'
                        });
                        if (response.ok) {
                            await loadBuilds();
                        } else {
                            alert('Failed to delete build.');
                        }
                    } catch (e) {
                        alert('Error connecting to the server.');
                    }
                }
            });
        });
    }

    function showSingleBuild(item: any, index: number) {
        const build = item.buildData;
        const content = document.getElementById('single-build-content');
        
        if (!content || !mylistView || !singleBuildView) return;

        content.innerHTML = \`
            <header class="single-build-header">
                <h1>\${escapeHtml(build.name)}</h1>
                <p>\${escapeHtml(build.description)}</p>
                <div class="price">Total: €\${build.totalPrice.toLocaleString()}</div>
            </header>

            <section class="score-cards" aria-label="Performance Scores">
                <div class="score-card">
                    <span class="score-value">\${build.scores?.gaming || 0}</span>
                    <span class="score-label">Gaming</span>
                </div>
                <div class="score-card">
                    <span class="score-value">\${build.scores?.workstation || 0}</span>
                    <span class="score-label">Workstation</span>
                </div>
                <div class="score-card">
                    <span class="score-value">\${build.scores?.value || 0}</span>
                    <span class="score-label">Value</span>
                </div>
            </section>

            <section class="component-detail-grid" aria-label="Detailed Component List" id="single-build-details-content">
                \${build.components.map((c: any) => renderComponentDetail(c)).join('')}
            </section>

            <div style="margin-top: 3rem; text-align: center; display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap;">
                <button class="btn btn-outline delete-build-btn-single" data-id="\${item.id || item.Id}" style="padding: 0.75rem 2rem; border-color: var(--danger-color); color: var(--danger-color);">Remove</button>
                <button class="btn btn-primary pdf-btn-single" style="padding: 0.75rem 2rem;">Download PDF</button>
            </div>
        \`;

        content.querySelector('.delete-build-btn-single')?.addEventListener('click', async (e) => {
            const id = (e.currentTarget as HTMLElement).getAttribute('data-id');
            if (confirm('Remove this build from your list?')) {
                try {
                    const response = await fetch(`http://${window.location.hostname}:5075/api/builds/${id}`, {
                        method: 'DELETE',
                        credentials: 'include'
                    });
                    if (response.ok) {
                        singleBuildView.style.display = 'none';
                        mylistView.style.display = 'block';
                        await loadBuilds();
                    } else {
                        alert('Failed to delete build.');
                    }
                } catch (e) {
                    alert('Error connecting to the server.');
                }
            }
        });

        content.querySelector('.pdf-btn-single')?.addEventListener('click', () => {
            const detailsContainer = content.querySelector('#single-build-details-content') as HTMLElement;
            downloadPDF(build, detailsContainer);
        });

        mylistView.style.display = 'none';
        singleBuildView.style.display = 'block';
        window.scrollTo(0, 0);
        content.querySelector('h1')?.focus();
    }

    function downloadPDF(build: Build, elementToClone: HTMLElement) {
        if (!elementToClone) return;
        
        const clone = elementToClone.cloneNode(true) as HTMLElement;
        const buttons = clone.querySelector('div[style*="margin-top"]'); 
        if (buttons) {
            clone.removeChild(buttons);
        }
        const inlineButtons = clone.querySelectorAll('button, a.btn');
        inlineButtons.forEach(btn => btn.remove());

        clone.style.backgroundColor = '#161b22';
        clone.style.color = '#c9d1d9';
        clone.style.padding = '20px';

        const opt = {
            margin:       1,
            filename:     `${build.name.replace(/\\s+/g, '_')}_Build.pdf`,
            image:        { type: 'jpeg', quality: 0.98 },
            html2canvas:  { scale: 2 },
            jsPDF:        { unit: 'in', format: 'letter', orientation: 'portrait' }
        };

        if (typeof html2pdf !== 'undefined') {
            html2pdf().set(opt).from(clone).save();
        } else {
            alert('PDF generation library not loaded.');
        }
    }
});
