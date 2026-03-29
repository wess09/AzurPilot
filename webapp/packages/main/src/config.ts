const yaml = require('yaml');
const fs = require('fs');
const path = require('path');

function findAlasPath() {
    // 优先尝试便携版路径，其次尝试当前工作目录
    let current = process.env.PORTABLE_EXECUTABLE_DIR || process.cwd();
    
    // 向上递归查找最多 5 级，寻找包含 config/deploy.yaml 的根目录
    for (let i = 0; i < 5; i++) {
        if (fs.existsSync(path.join(current, 'config/deploy.yaml'))) {
            return current;
        }
        const parent = path.dirname(current);
        if (parent === current) break; // 到达磁盘根目录
        current = parent;
    }
    return process.cwd(); // 保底返回
}

// export const alasPath = 'D:/AzurLaneAutoScript';
export const alasPath = findAlasPath();

const file = fs.readFileSync(path.join(alasPath, './config/deploy.yaml'), 'utf8');
const config = yaml.parse(file);
const PythonExecutable = config.Deploy.Python.PythonExecutable;
const WebuiPort = config.Deploy.Webui.WebuiPort.toString();

export const pythonPath = (path.isAbsolute(PythonExecutable) ? PythonExecutable : path.join(alasPath, PythonExecutable));
export const webuiUrl = `http://127.0.0.1:${WebuiPort}`;
export const webuiPath = 'gui.py';
export const webuiArgs = ['--port', WebuiPort, '--electron'];
export const dpiScaling = Boolean(config.Deploy.Webui.DpiScaling) || (config.Deploy.Webui.DpiScaling === undefined) ;
