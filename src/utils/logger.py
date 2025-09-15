# -*- coding: utf-8 -*-
"""
日志工具模块
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler


def setup_logger(name: str = __name__, level: int = logging.INFO, 
                log_file: str = 'logs/app.log') -> logging.Logger:
    """设置日志器"""
    
    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # 创建日志器
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # 如果已经有处理器，直接返回
    if logger.handlers:
        return logger
    
    # 创建格式化器
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（带轮转）
    file_handler = RotatingFileHandler(
        log_file, 
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger


def get_logger(name: str = __name__) -> logging.Logger:
    """获取日志器"""
    return logging.getLogger(name)


# 设置第三方库的日志级别
def configure_third_party_loggers():
    """配置第三方库的日志级别"""
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
