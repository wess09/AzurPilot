import {app, Menu, Tray, BrowserWindow, ipcMain, globalShortcut} from 'electron';
import {URL} from 'url';
import {PyShell} from '/@/pyshell';
import {webuiArgs, webuiPath, dpiScaling} from '/@/config';
import {join} from 'path';

const path = require('path');
const {existsSync} = require('fs');

const isSingleInstance = app.requestSingleInstanceLock();

if (!isSingleInstance) {
  app.quit();
  process.exit(0);
}

// Keep Chromium on the accelerated path instead of falling back to software rendering.
// `ignore-gpu-blocklist` bypasses Electron/Chromium's internal GPU blacklist,
// and `use-angle=d3d11` nudges Windows to use the Direct3D-backed ANGLE path.
app.commandLine.appendSwitch('ignore-gpu-blocklist');
app.commandLine.appendSwitch('enable-gpu-rasterization');
app.commandLine.appendSwitch('enable-zero-copy');
if (process.platform === 'win32') {
  app.commandLine.appendSwitch('use-angle', 'd3d11');
}

// Install "Vue.js devtools"
if (import.meta.env.MODE === 'development') {
  app.whenReady()
    .then(() => import('electron-devtools-installer'))
    .then(({default: installExtension, VUEJS_DEVTOOLS_BETA}) => installExtension(VUEJS_DEVTOOLS_BETA, {
      loadExtensionOptions: {
        allowFileAccess: true,
      },
    }))
    .catch(e => console.error('Failed install extension:', e));
}

/**
 * Load deploy settings and start Alas web server.
 */
let alas = new PyShell(webuiPath, webuiArgs);
alas.end(function (err: string) {
  // if (err) throw err;
});


let mainWindow: BrowserWindow | null = null;

const pickFirstExistingPath = (candidates: string[]) => {
  for (const candidate of candidates) {
    if (existsSync(candidate)) {
      return candidate;
    }
  }
  return candidates[0];
};

const createWindow = async () => {
  const preloadPath = pickFirstExistingPath([
    join(__dirname, '../../preload/dist/index.cjs'),
    join(__dirname, '../../packages/preload/dist/index.cjs'),
  ]);

  mainWindow = new BrowserWindow({
    width: 1280,
    height: 880,
    show: false, // Use 'ready-to-show' event to show window
    frame: false,
    icon: path.join(__dirname, './buildResources/icon.ico'),
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
      sandbox: false,
      preload: preloadPath,
    },
  });

  /**
   * If you install `show: true` then it can cause issues when trying to close the window.
   * Use `show: false` and listener events `ready-to-show` to fix these issues.
   *
   * @see https://github.com/electron/electron/issues/25012
   */
  mainWindow.on('ready-to-show', () => {
    mainWindow?.show();

    // Hide menu
    Menu.setApplicationMenu(null);

    if (import.meta.env.MODE === 'development') {
      mainWindow?.webContents.openDevTools();
    }
  });

  mainWindow.on('focus', function () {
    // Dev tools
    globalShortcut.register('Ctrl+Shift+I', function () {
      if (mainWindow?.webContents.isDevToolsOpened()) {
        mainWindow?.webContents.closeDevTools()
      } else {
        mainWindow?.webContents.openDevTools()
      }
    });
    // Refresh
    globalShortcut.register('Ctrl+R', function () {
      mainWindow?.reload()
    });
    globalShortcut.register('Ctrl+Shift+R', function () {
      mainWindow?.reload()
    });
  });
  mainWindow.on('blur', function () {
    globalShortcut.unregisterAll()
  });

  // Minimize, maximize, close window.
  ipcMain.on('window-tray', function () {
    mainWindow?.hide();
  });
  ipcMain.on('window-min', function () {
    mainWindow?.minimize();
  });
  ipcMain.on('window-max', function () {
    mainWindow?.isMaximized() ? mainWindow?.restore() : mainWindow?.maximize();
  });
  ipcMain.on('window-close', function () {
    alas.kill(function () {
      mainWindow?.close();
    })
  });

  // Tray
  const tray = new Tray(path.join(__dirname, 'icon.png'));
  const contextMenu = Menu.buildFromTemplate([
    {
      label: 'Show',
      click: function () {
        mainWindow?.show();
      }
    },
    {
      label: 'Hide',
      click: function () {
        mainWindow?.hide();
      }
    },
    {
      label: 'Exit',
      click: function () {
        alas.kill(function () {
          mainWindow?.close();
        })
      }
    }
  ]);
  tray.setToolTip('Alas');
  tray.setContextMenu(contextMenu);
  tray.on('click', () => {
    mainWindow?.isVisible() ? mainWindow?.hide() : mainWindow?.show()
  });
  tray.on('right-click', () => {
    tray.popUpContextMenu(contextMenu)
  });
};


// No DPI scaling
if (!dpiScaling) {
  app.commandLine.appendSwitch('high-dpi-support', '1');
  app.commandLine.appendSwitch('force-device-scale-factor', '1');
}


function loadURL() {
  /**
   * URL for main window.
   * Vite dev server for development.
   * `file://../renderer/index.html` for production and test
   */
  if (import.meta.env.MODE === 'development' && import.meta.env.VITE_DEV_SERVER_URL !== undefined) {
    mainWindow?.loadURL(import.meta.env.VITE_DEV_SERVER_URL);
    return;
  }

  const pagePath = pickFirstExistingPath([
    join(__dirname, '../../renderer/dist/index.html'),
    join(__dirname, '../../packages/renderer/dist/index.html'),
  ]);
  mainWindow?.loadFile(pagePath);
}


const readyListener = (data: any) => {
  const message = data.toString();
  console.log(message);
  if (message.includes('Application startup complete') || message.includes('bind on address') || message.includes('Uvicorn running on')) {
    alas.stdout.removeAllListeners('data');
    alas.stderr.removeAllListeners('data');
    loadURL();
  }
};

alas.stdout.on('data', readyListener);
alas.stderr.on('data', readyListener);


app.on('second-instance', () => {
  // Someone tried to run a second instance, we should focus our window.
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    if (!mainWindow.isVisible()) mainWindow.show();
    mainWindow.focus();
  }
});


app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});


app.whenReady()
  .then(createWindow)
  .catch((e) => console.error('Failed create window:', e));


// Auto-updates
if (import.meta.env.PROD) {
  app.whenReady()
    .then(() => import('electron-updater'))
    .then(({autoUpdater}) => autoUpdater.checkForUpdatesAndNotify())
    .catch((e) => console.error('Failed check updates:', e));
}
