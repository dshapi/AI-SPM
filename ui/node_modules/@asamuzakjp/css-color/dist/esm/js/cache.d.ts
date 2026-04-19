import { Options } from './typedef.js';
/**
 * CacheItem
 */
export declare class CacheItem {
    #private;
    constructor(item: unknown, isNull?: boolean);
    get item(): unknown;
    get isNull(): boolean;
}
/**
 * NullObject
 */
export declare class NullObject extends CacheItem {
    constructor();
}
/**
 * Generational Cache implementation
 */
export declare class GenerationalCache<K, V> {
    #private;
    constructor(max: number);
    get size(): number;
    get max(): number;
    set max(value: number);
    get(key: K): V | undefined;
    set(key: K, value: V): void;
    has(key: K): boolean;
    delete(key: K): void;
    clear(): void;
}
export declare const genCache: GenerationalCache<string, CacheItem>;
/**
 * set cache
 * @param key - cache key
 * @param value - value to cache
 * @returns void
 */
export declare const setCache: (key: string, value: unknown) => void;
/**
 * get cache
 * @param key - cache key
 * @returns cached item or false otherwise
 */
export declare const getCache: (key: string) => CacheItem | false;
/**
 * create cache key
 * @param keyData - key data
 * @param [opt] - options
 * @returns cache key
 */
export declare const createCacheKey: (keyData: Record<string, string>, opt?: Options) => string;
