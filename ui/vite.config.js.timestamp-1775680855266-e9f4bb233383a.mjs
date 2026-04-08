import "node:module";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import.meta.url;
var vite_config_default = defineConfig({
	plugins: [react()],
	server: {
		port: 3001,
		proxy: {
			"/api/chat/stream": {
				target: "http://localhost:8080",
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/api/, ""),
				configure: (proxy) => {
					proxy.on("proxyRes", (proxyRes) => {
						proxyRes.headers["x-accel-buffering"] = "no";
						proxyRes.headers["cache-control"] = "no-cache";
					});
				}
			},
			"/api": {
				target: "http://localhost:8080",
				changeOrigin: true,
				rewrite: (path) => path.replace(/^\/api/, "")
			}
		}
	},
	preview: { port: 3001 }
});
//#endregion
export { vite_config_default as default };

//# sourceMappingURL=data:application/json;charset=utf-8;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidml0ZS5jb25maWcuanMiLCJuYW1lcyI6W10sInNvdXJjZXMiOlsiL3Nlc3Npb25zL3dpemFyZGx5LWhhcHB5LWNvcmkvbW50L0FJU1BNL3VpL3ZpdGUuY29uZmlnLmpzIl0sInNvdXJjZXNDb250ZW50IjpbImltcG9ydCB7IGRlZmluZUNvbmZpZyB9IGZyb20gJ3ZpdGUnXG5pbXBvcnQgcmVhY3QgZnJvbSAnQHZpdGVqcy9wbHVnaW4tcmVhY3QnXG5cbmV4cG9ydCBkZWZhdWx0IGRlZmluZUNvbmZpZyh7XG4gIHBsdWdpbnM6IFtyZWFjdCgpXSxcbiAgc2VydmVyOiB7XG4gICAgcG9ydDogMzAwMSxcbiAgICBwcm94eToge1xuICAgICAgLy8gU1NFIHN0cmVhbWluZyByb3V0ZSDigJQgbXVzdCBjb21lIGJlZm9yZSB0aGUgZ2VuZXJpYyAvYXBpIGNhdGNoLWFsbFxuICAgICAgJy9hcGkvY2hhdC9zdHJlYW0nOiB7XG4gICAgICAgIHRhcmdldDogJ2h0dHA6Ly9sb2NhbGhvc3Q6ODA4MCcsXG4gICAgICAgIGNoYW5nZU9yaWdpbjogdHJ1ZSxcbiAgICAgICAgcmV3cml0ZTogKHBhdGgpID0+IHBhdGgucmVwbGFjZSgvXlxcL2FwaS8sICcnKSxcbiAgICAgICAgY29uZmlndXJlOiAocHJveHkpID0+IHtcbiAgICAgICAgICBwcm94eS5vbigncHJveHlSZXMnLCAocHJveHlSZXMpID0+IHtcbiAgICAgICAgICAgIHByb3h5UmVzLmhlYWRlcnNbJ3gtYWNjZWwtYnVmZmVyaW5nJ10gPSAnbm8nXG4gICAgICAgICAgICBwcm94eVJlcy5oZWFkZXJzWydjYWNoZS1jb250cm9sJ10gPSAnbm8tY2FjaGUnXG4gICAgICAgICAgfSlcbiAgICAgICAgfSxcbiAgICAgIH0sXG4gICAgICAnL2FwaSc6IHtcbiAgICAgICAgdGFyZ2V0OiAnaHR0cDovL2xvY2FsaG9zdDo4MDgwJyxcbiAgICAgICAgY2hhbmdlT3JpZ2luOiB0cnVlLFxuICAgICAgICByZXdyaXRlOiAocGF0aCkgPT4gcGF0aC5yZXBsYWNlKC9eXFwvYXBpLywgJycpLFxuICAgICAgfSxcbiAgICB9LFxuICB9LFxuICBwcmV2aWV3OiB7IHBvcnQ6IDMwMDEgfSxcbn0pXG4iXSwibWFwcGluZ3MiOiI7Ozs7QUFHQSxJQUFBLHNCQUFlLGFBQWE7Q0FDMUIsU0FBUyxDQUFDLE9BQU8sQ0FBQztDQUNsQixRQUFRO0VBQ04sTUFBTTtFQUNOLE9BQU87R0FFTCxvQkFBb0I7SUFDbEIsUUFBUTtJQUNSLGNBQWM7SUFDZCxVQUFVLFNBQVMsS0FBSyxRQUFRLFVBQVUsR0FBRztJQUM3QyxZQUFZLFVBQVU7QUFDcEIsV0FBTSxHQUFHLGFBQWEsYUFBYTtBQUNqQyxlQUFTLFFBQVEsdUJBQXVCO0FBQ3hDLGVBQVMsUUFBUSxtQkFBbUI7T0FDckM7O0lBRUo7R0FDRCxRQUFRO0lBQ04sUUFBUTtJQUNSLGNBQWM7SUFDZCxVQUFVLFNBQVMsS0FBSyxRQUFRLFVBQVUsR0FBRztJQUM5QztHQUNGO0VBQ0Y7Q0FDRCxTQUFTLEVBQUUsTUFBTSxNQUFNO0NBQ3hCLENBQUEifQ==