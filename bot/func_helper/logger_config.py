"""
logger_config - 

Author:susu
Date:2023/12/12
"""
import datetime
import pytz
import sys
from loguru import logger

# 转换为亚洲上海时区
shanghai_tz = pytz.timezone("Asia/Shanghai")
Now = datetime.datetime.now(shanghai_tz)
log_filename = f"log/log_{Now.strftime('%Y%m%d')}.txt"
log_format = "{time:YYYY-MM-DD HH:mm:ss.SSS ZZ} | {name} | {level} | {message}"

# 动态获取日志级别
def get_log_level():
    """根据配置获取日志级别"""
    try:
        # 延迟导入避免循环依赖
        import os
        import json
        
        config_path = "config.json"
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
                debug_log = config_data.get('debug_log', False)
                return "DEBUG" if debug_log else "INFO"
        else:
            # 配置文件不存在时返回默认级别
            return "INFO"
    except Exception:
        # 如果读取配置失败，默认使用INFO级别
        pass
    
    return "INFO"

# 初始化logger配置（默认INFO级别）
_default_config = {
    "sink": log_filename,
    "format": log_format,
    "level": "INFO",  # 先使用默认INFO级别
    "rotation": "00:00",
    "retention": "30 days"
}

# 添加默认配置（文件输出）
logger.add(**_default_config)

# 添加控制台输出（可选，便于开发调试）
logger.add(sys.stderr, format=log_format, level="INFO")

def reconfigure_logger():
    """重新配置logger，在config加载后调用"""
    try:
        # 移除所有现有的handler
        logger.remove()
        
        # 获取正确的日志级别
        log_level = get_log_level()
        
        # 重新添加文件logger
        final_config = {
            "sink": log_filename,
            "format": log_format,
            "level": log_level,
            "rotation": "00:00",
            "retention": "30 days"
        }
        logger.add(**final_config)
        
        # 重新添加控制台输出
        logger.add(sys.stderr, format=log_format, level=log_level)
        
    except Exception as e:
        # 如果重新配置失败，保持默认配置
        logger.add(**_default_config)
        logger.add(sys.stderr, format=log_format, level="INFO")

def logu(name):
    """返回一个绑定名称的日志实例"""
    return logger.bind(name=name)
