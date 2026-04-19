export class GenerationalCache {
    constructor(max: number);
    set max(value: number);
    get max(): number;
    get size(): number;
    get(key: any): any;
    set(key: any, value: any): void;
    has(key: any): boolean;
    delete(key: any): void;
    clear(): void;
    #private;
}
