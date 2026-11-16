/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** 置 "1" 时使用 src/mock/mock.ts 作为开发演示数据源（不请求后端）。 */
  readonly VITE_MOCK?: string;
  /** 开发期后端地址（供 vite dev server 代理 /api 使用）。 */
  readonly VITE_API_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}