//#region src/js/cache.ts
var MAX_CACHE = 1024;
/**
* CacheItem
*/
var CacheItem = class {
	#isNull;
	#item;
	constructor(item, isNull = false) {
		this.#item = item;
		this.#isNull = !!isNull;
	}
	get item() {
		return this.#item;
	}
	get isNull() {
		return this.#isNull;
	}
};
/**
* NullObject
*/
var NullObject = class extends CacheItem {
	constructor() {
		super(Symbol("null"), true);
	}
};
/**
* Generational Cache implementation
*/
var GenerationalCache = class {
	#max;
	#boundary;
	#current;
	#old;
	constructor(max) {
		this.#current = /* @__PURE__ */ new Map();
		this.#old = /* @__PURE__ */ new Map();
		if (Number.isFinite(max) && max > 4) {
			this.#max = max;
			this.#boundary = Math.ceil(max / 2);
		} else {
			this.#max = 4;
			this.#boundary = 2;
		}
	}
	get size() {
		return this.#current.size + this.#old.size;
	}
	get max() {
		return this.#max;
	}
	set max(value) {
		if (Number.isFinite(value) && value > 4) {
			this.#max = value;
			this.#boundary = Math.ceil(value / 2);
		} else {
			this.#max = 4;
			this.#boundary = 2;
		}
		this.#current.clear();
		this.#old.clear();
	}
	get(key) {
		let value = this.#current.get(key);
		if (value !== void 0) return value;
		value = this.#old.get(key);
		if (value !== void 0) {
			this.set(key, value);
			return value;
		}
	}
	set(key, value) {
		this.#current.set(key, value);
		if (this.#current.size >= this.#boundary) {
			this.#old = this.#current;
			this.#current = /* @__PURE__ */ new Map();
		}
	}
	has(key) {
		return this.#current.has(key) || this.#old.has(key);
	}
	delete(key) {
		this.#current.delete(key);
		this.#old.delete(key);
	}
	clear() {
		this.#current.clear();
		this.#old.clear();
	}
};
var genCache = new GenerationalCache(MAX_CACHE);
/**
* shared null object
*/
var sharedNullObject = new NullObject();
/**
* set cache
* @param key - cache key
* @param value - value to cache
* @returns void
*/
var setCache = (key, value) => {
	if (!key) return;
	if (value === null) genCache.set(key, sharedNullObject);
	else if (value instanceof CacheItem) genCache.set(key, value);
	else genCache.set(key, new CacheItem(value));
};
/**
* get cache
* @param key - cache key
* @returns cached item or false otherwise
*/
var getCache = (key) => {
	if (!key) return false;
	const item = genCache.get(key);
	if (item !== void 0) return item;
	return false;
};
/**
* helper function to sort object keys alphabetically
* @param obj - Object
* @returns stringified JSON
*/
var stringifySorted = (obj) => {
	const keys = Object.keys(obj);
	if (keys.length === 0) return "";
	keys.sort();
	let result = "";
	for (const key of keys) result += `${key}:${JSON.stringify(obj[key])};`;
	return result;
};
/**
* create cache key
* @param keyData - key data
* @param [opt] - options
* @returns cache key
*/
var createCacheKey = (keyData, opt = {}) => {
	if (!keyData || opt.customProperty && typeof opt.customProperty.callback === "function" || opt.dimension && typeof opt.dimension.callback === "function") return "";
	const namespace = keyData.namespace || "";
	const name = keyData.name || "";
	const value = keyData.value || "";
	if (!namespace && !name && !value) return "";
	return `${`${namespace}:${name}:${value}`}::${`${opt.format || ""}|${opt.colorSpace || ""}|${opt.colorScheme || ""}|${opt.currentColor || ""}|${opt.d50 ? "1" : "0"}|${opt.nullable ? "1" : "0"}|${opt.preserveComment ? "1" : "0"}|${opt.delimiter || ""}`}::${opt.customProperty ? stringifySorted(opt.customProperty) : ""}::${opt.dimension ? stringifySorted(opt.dimension) : ""}`;
};
//#endregion
export { CacheItem, NullObject, createCacheKey, getCache, setCache };

//# sourceMappingURL=cache.js.map