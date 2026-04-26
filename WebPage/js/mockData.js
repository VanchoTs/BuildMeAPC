export const mockComponents = [
    // CPUs
    { id: 'cpu1', type: 'CPU', brand: 'AMD', model: 'Ryzen 5 7600', price: 229, url: 'https://example.com/cpu1', specs: { cores: 6, threads: 12, socket: 'AM5' } },
    { id: 'cpu2', type: 'CPU', brand: 'Intel', model: 'Core i7-14700K', price: 409, url: 'https://example.com/cpu2', specs: { cores: 20, threads: 28, socket: 'LGA1700' } },
    { id: 'cpu3', type: 'CPU', brand: 'AMD', model: 'Ryzen 7 7800X3D', price: 369, url: 'https://example.com/cpu3', specs: { cores: 8, threads: 16, socket: 'AM5' } },
    
    // GPUs
    { id: 'gpu1', type: 'GPU', brand: 'NVIDIA', model: 'RTX 4060', price: 299, url: 'https://example.com/gpu1', specs: { vram: '8GB', tdp: '115W' } },
    { id: 'gpu2', type: 'GPU', brand: 'AMD', model: 'RX 7800 XT', price: 499, url: 'https://example.com/gpu2', specs: { vram: '16GB', tdp: '263W' } },
    { id: 'gpu3', type: 'GPU', brand: 'NVIDIA', model: 'RTX 4080 Super', price: 999, url: 'https://example.com/gpu3', specs: { vram: '16GB', tdp: '320W' } },
    
    // Motherboards
    { id: 'mb1', type: 'Motherboard', brand: 'MSI', model: 'PRO B650M-P', price: 119, url: 'https://example.com/mb1', specs: { socket: 'AM5', format: 'mATX' } },
    { id: 'mb2', type: 'Motherboard', brand: 'ASUS', model: 'ROG STRIX Z790-E', price: 379, url: 'https://example.com/mb2', specs: { socket: 'LGA1700', format: 'ATX' } },
    
    // RAM
    { id: 'ram1', type: 'RAM', brand: 'Corsair', model: 'Vengeance 32GB (2x16) DDR5-6000', price: 115, url: 'https://example.com/ram1', specs: { speed: '6000MHz', capacity: '32GB' } },
    
    // SSD
    { id: 'ssd1', type: 'SSD', brand: 'Samsung', model: '980 Pro 1TB', price: 99, url: 'https://example.com/ssd1', specs: { capacity: '1TB', type: 'NVMe Gen4' } },
    
    // PSU
    { id: 'psu1', type: 'PSU', brand: 'Corsair', model: 'RM750e', price: 99, url: 'https://example.com/psu1', specs: { wattage: '750W', efficiency: 'Gold' } },
    
    // Case
    { id: 'case1', type: 'Case', brand: 'NZXT', model: 'H5 Flow', price: 94, url: 'https://example.com/case1', specs: { color: 'Black', type: 'Mid Tower' } },
    
    // Cooler
    { id: 'cool1', type: 'Cooler', brand: 'Thermalright', model: 'Peerless Assassin 120 SE', price: 34, url: 'https://example.com/cool1', specs: { type: 'Air' } }
];
