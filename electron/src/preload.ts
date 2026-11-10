// The only thing the page can ask the shell for: where the backend is and its one-time token.
import { contextBridge, ipcRenderer } from "electron";

contextBridge.exposeInMainWorld("pdfValidation", {
  backendInfo: async () => {
    const result = await ipcRenderer.invoke("backend-info");
    if (!result.ok) throw new Error(result.error);
    return result.info as { url: string; token: string };
  },
});
