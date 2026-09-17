/// <reference types="vite/client" />

interface WindowOrWorkerGlobalScope {
  MonacoEnvironment?: { getWorker(moduleId: string, label: string): Worker };
}
