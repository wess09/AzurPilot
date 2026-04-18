import {contextBridge, ipcRenderer} from 'electron';

const apiKey = 'electron';
/**
 * @see https://github.com/electron/electron/issues/21437#issuecomment-573522360
 */
const api: ElectronApi = {
  versions: process.versions,
  windowControls: {
    tray() {
      ipcRenderer.send('window-tray');
    },
    minimize() {
      ipcRenderer.send('window-min');
    },
    maximize() {
      ipcRenderer.send('window-max');
    },
    close() {
      ipcRenderer.send('window-close');
    },
  },
};

/**
 * The "Main World" is the JavaScript context that your main renderer code runs in.
 * By default, the page you load in your renderer executes code in this world.
 *
 * @see https://www.electronjs.org/docs/api/context-bridge
 */
contextBridge.exposeInMainWorld(apiKey, api);
