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

async function saveBuild(build) {
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

document.addEventListener('DOMContentLoaded', async () => {
    const resultsContainer = document.getElementById('results-container');
    const comparisonContainer = document.getElementById('comparison-container');
    const resultsView = document.getElementById('results-view');
    const singleBuildView = document.getElementById('single-build-view');
    const backBtn = document.getElementById('back-to-results-btn');

    if (backBtn && resultsView && singleBuildView) {
        backBtn.addEventListener('click', () => {
            singleBuildView.style.display = 'none';
            resultsView.style.display = 'block';
            window.scrollTo(0, 0);
        });
    }

    // Comparison Mode Check: If results-container doesn't exist but comparison-container does,
    // we are likely on the dedicated compare.html page. 
    // We should NOT fetch new builds; just render what is in generatedBuilds.
    if (!resultsContainer && comparisonContainer) {
        const stored = localStorage.getItem('generatedBuilds');
        if (stored) {
            const builds = JSON.parse(stored);
            renderComparison(comparisonContainer, builds);
        }
        return;
    }

    const compareBtnContainer = document.getElementById('compare-btn-container');
    if (compareBtnContainer) compareBtnContainer.style.display = 'none';

    // Normal Results Mode
    const requirementsJson = localStorage.getItem('userRequirements');
    if (!requirementsJson) return;
    const requirements = JSON.parse(requirementsJson);

    let builds = [];
    try {
        const response = await fetch(
            `http://${window.location.hostname}:5075/api/builds/generate`,
            {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(requirements)
            }
        );
        if (!response.ok) {
            throw new Error(`Generate request failed: ${response.status}`);
        }
        builds = await response.json();
    } catch (err) {
        console.error('Failed to generate builds from API:', err);
        if (resultsContainer) {
            resultsContainer.innerHTML = `
                <div class="card">
                    <h3>Could not generate builds</h3>
                    <p>The build service is unreachable. Please try again shortly.</p>
                </div>`;
        }
        if (compareBtnContainer) compareBtnContainer.style.display = 'none';
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
        if (compareBtnContainer) compareBtnContainer.style.display = 'none';
        return;
    }

    if (compareBtnContainer) compareBtnContainer.style.display = 'block';
    localStorage.setItem('generatedBuilds', JSON.stringify(builds));

    if (resultsContainer) renderResults(resultsContainer, builds);
    if (comparisonContainer) renderComparison(comparisonContainer, builds);
});

function renderResults(container, builds) {
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
                <button class="btn btn-outline report-btn" data-id="${build.id}" style="flex: 1; border-color: var(--warning-color); color: var(--warning-color);">Report</button>
            </div>
        `;
        container.appendChild(card);
    });

    container.querySelectorAll('.view-details-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = e.target.getAttribute('data-id');
            const build = builds.find(b => b.id === id);
            if (build) showSingleBuild(build);
        });
    });

    container.querySelectorAll('.select-build-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = e.target.getAttribute('data-id');
            const build = builds.find(b => b.id === id);
            if (build) saveBuild(build);
        });
    });

    container.querySelectorAll('.pdf-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = e.target.getAttribute('data-id');
            const build = builds.find(b => b.id === id);
            if (build) downloadPDF(build);
        });
    });

    container.querySelectorAll('.report-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const id = e.target.getAttribute('data-id');
            const build = builds.find(b => b.id === id);
            const comment = prompt('Describe the issue with this build (incompatibility, better part available, etc.):');
            if (comment && build) {
                reportBuild(build, comment);
            }
        });
    });
}

function showSingleBuild(build) {
    const resultsView = document.getElementById('results-view');
    const singleBuildView = document.getElementById('single-build-view');
    const content = document.getElementById('single-build-content');
    
    if (!resultsView || !singleBuildView || !content) return;

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
            ${build.components.map(c => renderComponentDetail(c)).join('')}
        </section>

        <div style="margin-top: 3rem; text-align: center; display: flex; gap: 1rem; justify-content: center; flex-wrap: wrap;">
            <button class="btn btn-primary select-build-btn-bottom" style="padding: 0.75rem 2rem;">Save This Build</button>
            <button class="btn btn-primary pdf-btn-bottom" style="padding: 0.75rem 2rem;">Download PDF</button>
            <button class="btn btn-outline report-btn-bottom" style="padding: 0.75rem 2rem; border-color: var(--warning-color); color: var(--warning-color);">Report Issue</button>
            <button class="btn btn-outline" onclick="window.scrollTo(0, 0); document.getElementById('back-to-results-btn').click();" style="padding: 0.75rem 2rem;">Return to All Recommendations</button>
        </div>
    `;

    content.querySelector('.select-build-btn-bottom').addEventListener('click', () => saveBuild(build));
    content.querySelector('.pdf-btn-bottom').addEventListener('click', () => downloadPDF(build));
    content.querySelector('.report-btn-bottom').addEventListener('click', () => {
        const comment = prompt('Describe the issue with this build:');
        if (comment) reportBuild(build, comment);
    });

    resultsView.style.display = 'none';
    singleBuildView.style.display = 'block';
    window.scrollTo(0, 0);
    content.querySelector('h1').focus();
}

function renderComparison(container, builds) {
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
