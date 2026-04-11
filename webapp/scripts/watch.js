#!/usr/bin/node

const {createServer, build, createLogger} = require('vite');
const electronPath = require('electron');
const {spawn} = require('child_process');
const fs = require('fs');
const path = require('path');
const yaml = require('yaml');


/** @type 'production' | 'development' | 'test' */
const mode = process.env.MODE = process.env.MODE || 'development';


/** @type {import('vite').LogLevel} */
const LOG_LEVEL = 'warn';


// 读取 deploy.yaml 获取后端端口，注入给渲染进程
function getWebuiUrl() {
  try {
    const deployPath = path.resolve(__dirname, '../../config/deploy.yaml');
    const content = fs.readFileSync(deployPath, 'utf8');
    const config = yaml.parse(content);
    const port = config?.Deploy?.Webui?.WebuiPort ?? 22267;
    return `http://127.0.0.1:${port}`;
  } catch (e) {
    return 'http://127.0.0.1:22267';
  }
}

const VITE_WEBUI_URL = getWebuiUrl();


/** @type {import('vite').InlineConfig} */
const sharedConfig = {
  mode,
  build: {
    watch: {},
  },
  logLevel: LOG_LEVEL,
};


/**
 * @param configFile
 * @param writeBundle
 * @param name
 * @returns {Promise<import('vite').RollupOutput | Array<import('vite').RollupOutput> | import('vite').RollupWatcher>}
 */
const getWatcher = ({name, configFile, writeBundle}) => {
  return build({
    ...sharedConfig,
    configFile,
    plugins: [{name, writeBundle}],
  });
};


/**
 * Start or restart App when source files are changed
 * @param {import('vite').ViteDevServer} viteDevServer
 * @returns {Promise<import('vite').RollupOutput | Array<import('vite').RollupOutput> | import('vite').RollupWatcher>}
 */
const setupMainPackageWatcher = (viteDevServer) => {
  // Write a value to an environment variable to pass it to the main process.
  {
    const protocol = `http${viteDevServer.config.server.https ? 's' : ''}:`;
    const host = viteDevServer.config.server.host || 'localhost';
    const port = viteDevServer.config.server.port; // Vite searches for and occupies the first free port: 3000, 3001, 3002 and so on
    const path = '/';
    process.env.VITE_DEV_SERVER_URL = `${protocol}//${host}:${port}${path}`;
  }

  const logger = createLogger(LOG_LEVEL, {
    prefix: '[main]',
  });

  /** @type {ChildProcessWithoutNullStreams | null} */
  let spawnProcess = null;

  return getWatcher({
    name: 'reload-app-on-main-package-change',
    configFile: 'packages/main/vite.config.mjs',
    writeBundle() {
      if (spawnProcess !== null) {
        spawnProcess.kill('SIGINT');
        spawnProcess = null;
      }

      spawnProcess = spawn(String(electronPath), ['.']);

      spawnProcess.stdout.on('data', d => d.toString().trim() && logger.warn(d.toString(), {timestamp: true}));
      spawnProcess.stderr.on('data', d => d.toString().trim() && logger.error(d.toString(), {timestamp: true}));
    },
  });
};


/**
 * Start or restart App when source files are changed
 * @param {import('vite').ViteDevServer} viteDevServer
 * @returns {Promise<import('vite').RollupOutput | Array<import('vite').RollupOutput> | import('vite').RollupWatcher>}
 */
const setupPreloadPackageWatcher = (viteDevServer) => {
  return getWatcher({
    name: 'reload-page-on-preload-package-change',
    configFile: 'packages/preload/vite.config.mjs',
    writeBundle() {
      viteDevServer.ws.send({
        type: 'full-reload',
      });
    },
  });
};

(async () => {
  try {
    const viteDevServer = await createServer({
      ...sharedConfig,
      configFile: 'packages/renderer/vite.config.mjs',
      define: {
        'import.meta.env.VITE_WEBUI_URL': JSON.stringify(VITE_WEBUI_URL),
      },
    });

    await viteDevServer.listen();

    await setupPreloadPackageWatcher(viteDevServer);
    await setupMainPackageWatcher(viteDevServer);
  } catch (e) {
    console.error(e);
    process.exit(1);
  }
})();
