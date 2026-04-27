import { Build, UserRequirements, Component } from './types.js';

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

document.addEventListener('DOMContentLoaded', async () => {
    const resultsContainer = document.getElementById('results-container');
    const comparisonContainer = document.getElementById('comparison-container');
    const resultsView = document.getElementById('results-view');
    const singleBuildView = document.getElementById('single-build-view');
    const backBtn = document.getElementById('back-to-results-btn');

    const requirementsJson = localStorage.getItem('userRequirements');
    if (!requirementsJson) return;
    const requirements: UserRequirements = JSON.parse(requirementsJson);

    let builds: Build[] = [];
    try {
        builds = await fetchBuilds(requirements);
    } catch (err) {
        console.error('Failed to generate builds from API:', err);
        if (resultsContainer) {
            resultsContainer.innerHTML = `
                <div class="card">
                    <h3>Could not generate builds</h3>
                    <p>The build service is unreachable. Please try again shortly.</p>
                </div>`;
        }
        return;
    }

    if (builds.length === 0) {
        if (resultsContainer) {
            resultsContainer.innerHTML = `
                <div class="card">
                    <h3>No compatible builds found</h3>
                    <p>Try widening your budget or relaxing brand/Wi-Fi filters.</p>
                </div>`;
        }
        return;
    }

    localStorage.setItem('generatedBuilds', JSON.stringify(builds));

    if (resultsContainer) renderResults(resultsContainer, builds);
    if (comparisonContainer) renderComparison(comparisonContainer, builds);

    if (backBtn && resultsView && singleBuildView) {
        backBtn.addEventListener('click', () => {
            singleBuildView.style.display = 'none';
            resultsView.style.display = 'block';
            window.scrollTo(0, 0);
        });
    }
});

async function fetchBuilds(req: UserRequirements): Promise<Build[]> {
    const response = await fetch(
        `http://${window.location.hostname}:5075/api/builds/generate`,
        {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(req)
        }
    );
    if (!response.ok) {
        throw new Error(`Generate request failed: ${response.status}`);
    }
    return await response.json() as Build[];
}

function escapeHtml(text: string | number | undefined | null) {
    if (text === undefined || text === null) return '';
    const div = document.createElement('div');
    div.textContent = text.toString();
    return div.innerHTML;
}

function formatSpecValue(key: string, value: any): string {
    if (value === null || value === undefined || value === '') return '';
    
    let displayValue = value;
    if (typeof value === 'number') {
        // Round to 1 decimal place
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

function getCoreSpecs(build: Build): string {
    const cpu = build.components.find(c => c.type === 'CPU');
    const gpu = build.components.find(c => c.type === 'GPU');
    const ram = build.components.find(c => c.type === 'RAM');
    const ssd = build.components.find(c => c.type === 'SSD');
    const psu = build.components.find(c => c.type === 'PSU');

    const specs = [];
    if (cpu) specs.push(`${cpu.specs.cores} Cores`);
    if (gpu) specs.push(`${gpu.specs.vramGb}GB VRAM`);
    if (ram) specs.push(`${ram.specs.memoryAmount}`);
    if (ssd) specs.push(`${ssd.specs.storageSizeGb}GB SSD`);
    if (psu) specs.push(`${psu.specs.powerW}W`);

    return specs.join(' • ');
}

/**
 * Renders the build recommendations into the UI cards.
 * Includes event listeners for viewing details, saving, and PDF export.
 */
function renderResults(container: HTMLElement, builds: Build[]) {
    container.innerHTML = '';
    builds.forEach(build => {
        const card = document.createElement('article'); 
        card.className = 'card build-card';
        card.innerHTML = `
            <h3>${escapeHtml(build.name)}</h3>
            <p style="margin-bottom: 0.5rem;">${escapeHtml(build.description)}</p>
            <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 1rem;">${escapeHtml(getCoreSpecs(build))}</p>
            
            <div class="price-tag">€${build.totalPrice.toLocaleString()}</div>
            
            <ul class="component-list" aria-label="Component summary">
                ${build.components.slice(0, 4).map(c => `
                    <li>
                        <span class="component-type">${escapeHtml(c.type)}</span>
                        <span>${escapeHtml(c.brand)} ${escapeHtml(c.model)}</span>
                    </li>
                `).join('')}
                <li style="border-bottom: none; color: var(--accent-color); font-style: italic;">+ ${build.components.length - 4} more components</li>
            </ul>
            
            <div style="margin-top: 1.5rem; display: flex; gap: 1rem; flex-wrap: wrap;">
                <button class="btn btn-outline view-details-btn" data-id="${build.id}" style="flex: 1;">View Details</button>
                <button class="btn btn-primary select-build-btn" data-id="${build.id}" style="flex: 1;">Save</button>
                <button class="btn btn-primary pdf-btn" data-id="${build.id}" style="flex: 1;">Download PDF</button>
            </div>
        \`;
        container.appendChild(card);
    });

    // Event Listeners for Summary Cards
    container.querySelectorAll('.view-details-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = (e.target as HTMLElement).getAttribute('data-id');
            const build = builds.find(b => b.id === id);
            if (build) showSingleBuild(build);
        });
    });

    container.querySelectorAll('.select-build-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = (e.target as HTMLElement).getAttribute('data-id');
            const build = builds.find(b => b.id === id);
            if (build) saveBuild(build);
        });
    });

    container.querySelectorAll('.pdf-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = (e.target as HTMLElement).getAttribute('data-id');
            const build = builds.find(b => b.id === id);
            if (build) {
                const card = (e.target as HTMLElement).closest('.build-card');
                downloadPDF(build, card as HTMLElement);
            }
        });
    });
}

function showSingleBuild(build: Build) {
    const resultsView = document.getElementById('results-view');
    const singleBuildView = document.getElementById('single-build-view');
    const content = document.getElementById('single-build-content');
    
    if (!resultsView || !singleBuildView || !content) return;

    content.innerHTML = \`
        <header class="single-build-header">
            <h1>\${escapeHtml(build.name)}</h1>
            <p>\${escapeHtml(build.description)}</p>
            <div class="price">Total: €\${build.totalPrice.toLocaleString()}</div>
            <button class="btn btn-primary select-build-btn" data-id="\${build.id}" style="margin-top: 1rem; padding: 1rem 3rem;">Save This Build to My List</button>
        </header>

        <section class="score-cards" aria-label="Performance Scores">
            <div class="score-card">
                <span class="score-value">\${build.scores.gaming}</span>
                <span class="score-label">Gaming</span>
            </div>
            <div class="score-card">
                <span class="score-value">\${build.scores.workstation}</span>
                <span class="score-label">Workstation</span>
            </div>
            <div class="score-card">
                <span class="score-value">\${build.scores.value}</span>
                <span class="score-label">Value</span>
            </div>
        </section>

        <section class="component-detail-grid" aria-label="Detailed Component List" id="single-build-details-content">
            \${build.components.map(c => renderComponentDetail(c)).join('')}
        </section>

        <div style="margin-top: 3rem; text-align: center; display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap;">
            <button class="btn btn-primary select-build-btn" data-id="\${build.id}" style="padding: 0.75rem 2rem;">Save This Build</button>
            <button class="btn btn-primary pdf-btn" style="padding: 0.75rem 2rem;">Download PDF</button>
            <button class="btn btn-outline" onclick="window.scrollTo(0, 0); document.getElementById('back-to-results-btn').click();" style="padding: 0.75rem 2rem;">Return to All Recommendations</button>
        </div>
    \`;

    // Re-attach save listener for the big buttons
    content.querySelectorAll('.select-build-btn').forEach(btn => {
        btn.addEventListener('click', () => saveBuild(build));
    });
    content.querySelector('.pdf-btn')?.addEventListener('click', () => {
        const detailsContainer = content.querySelector('#single-build-details-content') as HTMLElement;
        downloadPDF(build, detailsContainer);
    });

    resultsView.style.display = 'none';
    singleBuildView.style.display = 'block';
    window.scrollTo(0, 0);
    content.querySelector('h1')?.focus();
}

function renderComponentDetail(c: Component): string {
    const specs = Object.entries(c.specs)
        .filter(([_, v]) => v !== null && v !== '' && v !== undefined)
        .map(([k, v]) => {
            const label = SPEC_LABELS[k] || k;
            const formattedValue = formatSpecValue(k, v);
            return `<span class="spec-pill"><strong>${escapeHtml(label)}:</strong> ${escapeHtml(formattedValue)}</span>`;
        })
        .join('');

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
                <div class="comp-price">€${c.price.toLocaleString()}</div>
                <a href="${c.url || '#'}" target="_blank" class="btn btn-outline" style="font-size: 0.8rem; padding: 0.5rem 1rem;">
                    View on pic.bg ↗
                </a>
            </div>
        </div>
    `;
}

async function saveBuild(build: Build) {
    const userJson = localStorage.getItem('user');
    if (!userJson) {
        localStorage.setItem('pendingBuildToSave', JSON.stringify(build));
        alert('You must be logged in to save builds!');
        window.location.href = 'login.html';
        return;
    }

    try {
        const response = await fetch(`http://${window.location.hostname}:5075/api/builds`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify(build)
        });

        if (response.ok) {
            alert('Build saved to My List!');
        } else {
            alert('Failed to save build.');
        }
    } catch (err) {
        console.error(err);
        alert('Could not connect to the server to save the build.');
    }
}

/**
 * Generates a PDF document for a specific build by cloning the DOM element,
 * stripping interactive elements (buttons), and applying print-friendly styles.
 * Uses html2pdf.js for client-side generation.
 */
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

function renderComparison(container: HTMLElement, builds: Build[]) {
    const componentTypes = ['CPU', 'GPU', 'RAM', 'Motherboard', 'SSD', 'PSU', 'Case', 'Cooler'];

    const html = `
        <table>
            <thead>
                <tr>
                    <th>Specification</th>
                    ${builds.map(b => `<th>${escapeHtml(b.name)}</th>`).join('')}
                </tr>
            </thead>
            <tbody>
                <tr>
                    <td class="spec-name">Total Price</td>
                    ${builds.map(b => `<td><strong>€${b.totalPrice.toLocaleString()}</strong></td>`).join('')}
                </tr>
                ${componentTypes.map(type => `
                    <tr>
                        <td class="spec-name">${type}</td>
                        ${builds.map(b => {
                            const comp = b.components.find(c => c.type === type);
                            return `<td>${comp ? escapeHtml(comp.brand + ' ' + comp.model) : 'N/A'}</td>`;
                        }).join('')}
                    </tr>
                `).join('')}
                <tr>
                    <td class="spec-name">Gaming Score</td>
                    ${builds.map(b => `<td>${b.scores.gaming}/100</td>`).join('')}
                </tr>
                <tr>
                    <td class="spec-name">Workstation Score</td>
                    ${builds.map(b => `<td>${b.scores.workstation}/100</td>`).join('')}
                </tr>
                <tr>
                    <td class="spec-name">Value Score</td>
                    ${builds.map(b => `<td>${b.scores.value}/100</td>`).join('')}
                </tr>
            </tbody>
        </table>
    `;
    container.innerHTML = html;
}
