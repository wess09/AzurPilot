#!/usr/bin/env python3
"""
测试修复后的 YAML 解析功能
"""
import os
import sys

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from deploy.utils import poor_yaml_read
from deploy.config import DeployConfig

# 测试 poor_yaml_read 函数
def test_poor_yaml_read():
    print("=== 测试 poor_yaml_read 函数 ===")
    # 使用 os.path.join 和 __file__ 确保路径正确性
    template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "deploy", "template")
    print(f"模板文件路径: {template_path}")
    print(f"文件是否存在: {os.path.exists(template_path)}")
    config = poor_yaml_read(template_path)
    
    # 检查是否解析出了嵌套结构
    if "Deploy" in config and isinstance(config["Deploy"], dict):
        print("OK: 成功解析出 Deploy 嵌套结构")
        if "Webui" in config["Deploy"] and isinstance(config["Deploy"]["Webui"], dict):
            print("OK: 成功解析出 Webui 嵌套结构")
            if "WebuiHost" in config["Deploy"]["Webui"]:
                print(f"OK: WebuiHost 配置: {config['Deploy']['Webui']['WebuiHost']}")
            else:
                print("ERROR: 未找到 WebuiHost 配置")
        else:
            print("ERROR: 未解析出 Webui 嵌套结构")
    else:
        print("ERROR: 未解析出 Deploy 嵌套结构")

# 测试 DeployConfig 类
def test_deploy_config():
    print("\n=== 测试 DeployConfig 类 ===")
    deploy_config = DeployConfig()
    
    # 检查 WebuiHost 属性
    if hasattr(deploy_config, "WebuiHost"):
        print(f"OK: WebuiHost 属性值: {deploy_config.WebuiHost}")
        if deploy_config.WebuiHost == "0.0.0.0":
            print("OK: WebuiHost 配置正确读取为 0.0.0.0")
        else:
            print(f"ERROR: WebuiHost 配置读取错误: {deploy_config.WebuiHost}")
    else:
        print("ERROR: 未找到 WebuiHost 属性")

if __name__ == "__main__":
    test_poor_yaml_read()
    test_deploy_config()
    print("\n测试完成！")