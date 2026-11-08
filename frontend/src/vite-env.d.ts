/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional absolute API origin. Unset = same origin (relative URLs). */
  readonly VITE_API_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
