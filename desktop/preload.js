const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("orbDesktop", {
  onStatus: (cb) => {
    ipcRenderer.on("status", (_event, message) => cb(message));
  },
  pickDirectory: (opts) => ipcRenderer.invoke("pick-directory", opts || {}),
  getApiBaseUrl: () => ipcRenderer.invoke("get-api-base-url"),
  revealInFolder: (filePath) =>
    ipcRenderer.invoke("reveal-in-folder", filePath),
  isDesktop: true,
});
