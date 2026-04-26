const TOTAL_STEPS = 7;
const RESOLUTION_STEP = 5;

document.addEventListener('DOMContentLoaded', () => {
    const form = document.getElementById('build-form');
    if (!form) return;

    const steps = document.querySelectorAll('.form-step');
    const nextButtons = document.querySelectorAll('.next-btn');
    const prevButtons = document.querySelectorAll('.prev-btn');
    const optionCards = document.querySelectorAll('.option-card');

    let currentStep = 1;

    optionCards.forEach(card => {
        card.addEventListener('click', () => {
            if (card.classList.contains('locked')) return;
            const target = card.dataset.target;
            const value = card.dataset.value;

            if (target) {
                const grid = card.parentElement;
                if (grid) {
                    grid.querySelectorAll('.option-card').forEach(c =>
                        c.classList.remove('selected'));
                }
                card.classList.add('selected');
                const inputId = target === 'cpuBrandPref' ? 'cpu-brand-input' : 'gpu-brand-input';
                document.getElementById(inputId).value = value ?? '';
                return;
            }

            const parent = card.parentElement;
            if (!parent) return;
            parent.querySelectorAll('.option-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');

            const input = parent.nextElementSibling;
            if (input && input.tagName === 'INPUT' && value !== undefined) {
                input.value = value;
            }
        });
    });

    nextButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            if (validateStep(currentStep)) {
                changeStep(nextStep(currentStep, +1));
            }
        });
    });

    form.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            if (currentStep < TOTAL_STEPS) {
                if (validateStep(currentStep)) {
                    changeStep(nextStep(currentStep, +1));
                }
            } else {
                form.dispatchEvent(new Event('submit'));
            }
        }
    });

    prevButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            changeStep(nextStep(currentStep, -1));
        });
    });

    function changeStep(newStep) {
        steps.forEach(s => s.classList.remove('active'));
        const target = document.querySelector(`.form-step[data-step="${newStep}"]`);
        if (target) {
            target.classList.add('active');
            currentStep = newStep;
            applyBudgetLocks();
        }
    }

    function applyBudgetLocks() {
        const budget = parseInt(document.getElementById('budget').value);
        if (isNaN(budget)) return;
        ['ram-options', 'storage-options'].forEach(gridId => {
            const grid = document.getElementById(gridId);
            if (!grid) return;
            const inputId = gridId === 'ram-options' ? 'ram-input' : 'storage-input';
            const input = document.getElementById(inputId);
            const cards = Array.from(grid.querySelectorAll('.option-card'));
            let bestAffordable = null;
            cards.forEach(card => {
                const min = parseInt(card.dataset.minBudget || '0');
                const locked = budget < min;
                card.classList.toggle('locked', locked);
                if (!locked) bestAffordable = card;
            });
            const selectedCard = grid.querySelector('.option-card.selected');
            if (!selectedCard || selectedCard.classList.contains('locked')) {
                cards.forEach(c => c.classList.remove('selected'));
                if (bestAffordable) {
                    bestAffordable.classList.add('selected');
                    if (input) input.value = bestAffordable.dataset.value;
                }
            }
        });
    }

    function nextStep(from, dir) {
        let s = from + dir;
        const usage = document.getElementById('usage-input')?.value;
        while (s === RESOLUTION_STEP && usage !== 'gaming' && s > 0 && s <= TOTAL_STEPS) {
            s += dir;
        }
        return Math.max(1, Math.min(TOTAL_STEPS, s));
    }

    function validateStep(step) {
        switch (step) {
            case 1: {
                const budget = parseInt(document.getElementById('budget').value);
                if (isNaN(budget) || budget < 500) {
                    alert('Please enter a total budget of at least €500.');
                    return false;
                }
                return true;
            }
            case 2:
                if (!document.getElementById('usage-input').value) {
                    alert('Please select a primary usage.');
                    return false;
                }
                return true;
            case 3:
                if (!document.getElementById('ram-input').value) {
                    alert('Please pick a RAM capacity.');
                    return false;
                }
                return true;
            case 4:
                if (!document.getElementById('storage-input').value) {
                    alert('Please pick a storage size.');
                    return false;
                }
                return true;
            case 5: {
                const usage = document.getElementById('usage-input').value;
                if (usage === 'gaming' &&
                    !document.getElementById('resolution-input').value) {
                    alert('Please pick a target resolution.');
                    return false;
                }
                return true;
            }
            default:
                return true;
        }
    }

    form.addEventListener('submit', (e) => {
        e.preventDefault();

        const usage = document.getElementById('usage-input').value;
        const resolutionValue = document.getElementById('resolution-input').value;
        const cpuBrand = document.getElementById('cpu-brand-input').value;
        const gpuBrand = document.getElementById('gpu-brand-input').value;

        const requirements = {
            budget: parseInt(document.getElementById('budget').value),
            usage,
            storageGb: parseInt(document.getElementById('storage-input').value) || 1000,
            ramGb: parseInt(document.getElementById('ram-input').value) || 16,
            wifiRequired: document.getElementById('wifi-input').checked
        };

        if (usage === 'gaming' && resolutionValue) {
            requirements.resolution = resolutionValue;
        }
        if (cpuBrand) {
            requirements.cpuBrandPref = cpuBrand;
        }
        if (gpuBrand) {
            requirements.gpuBrandPref = gpuBrand;
        }

        localStorage.setItem('userRequirements', JSON.stringify(requirements));
        window.location.href = 'results.html';
    });
});
