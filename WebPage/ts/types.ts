export type UsageType = 'gaming' | 'workstation' | 'general';
export type ResolutionType = '1080p60' | '1080p144' | '1440p144' | '4k60';
export type CpuBrandPref = 'AMD' | 'Intel' | '';
export type GpuBrandPref = 'NVIDIA' | 'AMD' | '';

export interface Component {
    id: string;
    type: 'CPU' | 'GPU' | 'RAM' | 'Motherboard' | 'SSD' | 'PSU' | 'Case' | 'Cooler';
    brand: string;
    model: string;
    price: number;
    url?: string;
    specs: Record<string, string | number>;
}

export interface Build {
    id: string;
    name: string;
    description: string;
    totalPrice: number;
    components: Component[];
    scores: {
        gaming: number;
        workstation: number;
        value: number;
    };
}

export interface UserRequirements {
    budget: number;
    usage: UsageType;
    storageGb: number;
    resolution?: ResolutionType;
    ramGb: number;
    cpuBrandPref?: CpuBrandPref;
    gpuBrandPref?: GpuBrandPref;
    wifiRequired: boolean;
}
