import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";
import frappeui from "frappe-ui/vite";

// base '/app/': the bridge serves dist/ at /app and /app/*.
export default defineConfig({
  base: "/app/",
  plugins: [
    vue(),
    // frappe-ui 组件（如 Spinner.vue）里的 ~icons/lucide/* 虚拟导入
    // 依赖该插件解析；frappeProxy/jinjaBootData/buildConfig 是 Frappe
    // 后端专属的，这里只读 bridge API，全部关闭。
    frappeui({
      lucideIcons: true,
      frappeProxy: false,
      jinjaBootData: false,
      buildConfig: false,
    }),
  ],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8763",
    },
  },
});
