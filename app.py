#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import signal

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.core.bot import JenkinsApprovalBot
from src.utils.logger import setup_logger, configure_third_party_loggers
from src.services.config_validator import ConfigurationError

logger = setup_logger('jenkins_approval_bot')
configure_third_party_loggers()
bot_instance = None


def signal_handler(signum, frame):
    logger.info("收到停止信号 {}，正在关闭服务...".format(signum))
    if bot_instance:
        bot_instance.stop()
    sys.exit(0)

def validate_environment():
    config_file = os.path.join(os.path.dirname(__file__), "config", "app.json")
    if not os.path.exists(config_file):
        logger.error("❌ 缺少配置文件: {}".format(config_file))
        return False
    return True

def main():
    global bot_instance
    
    try:
        logger.info("🚀 启动Jenkins审批机器人...")
        
        if sys.version_info < (3, 6):
            logger.error("❌ 需要Python 3.6或更高版本")
            sys.exit(1)
        
        if not validate_environment():
            sys.exit(1)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        bot_instance = JenkinsApprovalBot()
        
        if not bot_instance.start():
            logger.error("❌ 服务启动失败")
            sys.exit(1)
        
        try:
            bot_instance.stop_event.wait()
        except KeyboardInterrupt:
            logger.info("🛑 收到键盘中断信号...")
    
    except ConfigurationError as e:
        logger.error("❌ 配置错误: {}".format(str(e)))
        sys.exit(1)
        
    except Exception as e:
        logger.error("❌ 服务运行失败: {}".format(str(e)))
        sys.exit(1)
    finally:
        if bot_instance:
            bot_instance.stop()


if __name__ == '__main__':
    main()
