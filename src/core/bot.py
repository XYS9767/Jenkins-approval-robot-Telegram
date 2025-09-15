# -*- coding: utf-8 -*-

import os
import threading
from threading import Event

from telegram.ext import Updater

from ..services.config_service import config_service
from ..services.permission_service import permission_service
from ..services.jenkins_service import JenkinsService
from ..services.database_service import initialize_database_service
from ..services.config_validator import ConfigurationError
from ..handlers.telegram_handler import TelegramHandler
from ..handlers.api_handler import APIHandler
from ..core.approval_manager import ApprovalManager
from ..utils.logger import get_logger

logger = get_logger(__name__)

class JenkinsApprovalBot:
    
    def __init__(self):
        config_service.load_config_files()
        initialize_database_service(config_service)
        
        telegram_config = config_service.get_telegram_config()
        jenkins_config = config_service.get_jenkins_config()
        service_config = config_service.get_service_config()
        
        self.bot_token = telegram_config.get('bot_token')
        self.chat_id = telegram_config.get('chat_id')
        self.proxy_config = telegram_config.get('proxy', {})
        
        if not self.bot_token:
            raise ConfigurationError("❌ Telegram bot_token 未配置，请在 config/app.json 中设置")
        if not self.chat_id:
            raise ConfigurationError("❌ Telegram chat_id 未配置，请在 config/app.json 中设置")
        
        self.jenkins_config = {
            'url': jenkins_config.get('url'),
            'username': jenkins_config.get('username'),
            'password': jenkins_config.get('password'),
            'timeout': jenkins_config.get('api_timeout', 30)
        }
        
        if not self.jenkins_config['url']:
            raise ConfigurationError("❌ Jenkins URL 未配置，请在 config/app.json 中设置")
        if not self.jenkins_config['username']:
            raise ConfigurationError("❌ Jenkins username 未配置，请在 config/app.json 中设置")
        if not self.jenkins_config['password']:
            raise ConfigurationError("❌ Jenkins password 未配置，请在 config/app.json 中设置")
        
        self.updater = None
        self.jenkins_service = JenkinsService(self.jenkins_config)
        self.approval_manager = ApprovalManager(self.jenkins_service)
        self.telegram_handler = None
        self.api_handler = None
        self.bot_thread = None
        self.flask_thread = None
        self.running = False
        self.stop_event = Event()
    
    def initialize(self):
        try:
            if not self.bot_token:
                raise Exception("未配置TELEGRAM_BOT_TOKEN")
            
            if self.proxy_config.get('enabled', False):
                proxy_url = self.proxy_config.get('url')
                if proxy_url:
                    logger.info("使用代理服务器: {}".format(proxy_url))
                    try:
                        os.environ['HTTPS_PROXY'] = proxy_url
                        os.environ['HTTP_PROXY'] = proxy_url
                        logger.info("已设置环境变量代理: HTTP_PROXY={}, HTTPS_PROXY={}".format(proxy_url, proxy_url))
                        self.updater = Updater(token=self.bot_token, use_context=True)
                    except Exception as proxy_error:
                        logger.warning("代理配置失败，使用直连: {}".format(str(proxy_error)))
                        self.updater = Updater(token=self.bot_token, use_context=True)
                else:
                    logger.error("代理已启用但未配置URL")
                    self.updater = Updater(token=self.bot_token, use_context=True)
            else:
                logger.info("未启用代理，使用直连")
                self.updater = Updater(token=self.bot_token, use_context=True)
            self.telegram_handler = TelegramHandler(
                bot=self.updater.bot,
                chat_id=self.chat_id,
                approval_manager=self.approval_manager
            )
            self.telegram_handler.setup_handlers(self.updater.dispatcher)
            
            self.api_handler = APIHandler(self.approval_manager)
            self.api_handler.set_telegram_handler(self.telegram_handler)
            
            # 🔥 关键修复：让TelegramHandler也能访问APIHandler，确保事件触发统一
            self.telegram_handler.set_api_handler(self.api_handler)
            
            config_service.start_config_monitor()
            permission_service.load_users()
            
            logger.info("Jenkins审批机器人初始化完成")
            return True
            
        except Exception as e:
            logger.error("初始化失败: {}".format(str(e)))
            return False
    
    def start(self):
        try:
            if not self.initialize():
                return False
            
            self.running = True
            
            # 启动Telegram机器人线程
            self.bot_thread = threading.Thread(target=self._run_telegram_bot, daemon=True)
            self.bot_thread.start()
            
            # 启动Flask API线程
            self.flask_thread = threading.Thread(target=self._run_api_server, daemon=True)
            self.flask_thread.start()
            
            # 显示启动信息
            self._show_startup_info()
            
            return True
            
        except Exception as e:
            logger.error("启动服务失败: {}".format(str(e)))
            return False
    
    def stop(self):
        try:
            self.running = False
            self.stop_event.set()
            
            if self.updater:
                self.updater.stop()
                logger.info("Telegram机器人已停止")
            
            config_service.stop_config_monitor()
            logger.info("配置监控已停止")
            
            logger.info("服务已停止")
            
        except Exception as e:
            logger.error("停止服务时出错: {}".format(str(e)))
    
    def _run_telegram_bot(self):
        try:
            logger.info("启动Telegram机器人...")
            self.updater.start_polling(timeout=10, read_latency=2, clean=True)
            logger.info("Telegram机器人连接成功")
            self.stop_event.wait()
        except Exception as e:
            logger.error("Telegram机器人运行失败: {}".format(str(e)))
    
    def _run_api_server(self):
        try:
            service_config = config_service.get_service_config()
            port = service_config.get('port') or int(os.getenv('PORT', 8770))
            host = service_config.get('host') or os.getenv('HOST', '0.0.0.0')
            debug = service_config.get('debug', False)
            
            logger.info("启动Flask API服务: http://{}:{}".format(host, port))
            
            if self.api_handler:
                self.api_handler.app.run(
                    host=host, 
                    port=port, 
                    debug=debug, 
                    use_reloader=False, 
                    threaded=True
                )
        except Exception as e:
            logger.error("Flask API运行失败: {}".format(str(e)))
    
    def _show_startup_info(self):
        service_config = config_service.get_service_config()
        port = service_config.get('port') or int(os.getenv('PORT', 8770))
        host = service_config.get('host') or os.getenv('HOST', '0.0.0.0')
        
        logger.info("🚀 Jenkins审批机器人启动完成")
        logger.info("📱 Telegram机器人: 已连接到群组 {}".format(self.chat_id))
        logger.info("🌐 API服务: http://{}:{}".format(host, port))
        logger.info("📞 按 Ctrl+C 停止服务")
    
    def get_status(self):
        return {
            'running': self.running,
            'telegram_connected': self.updater is not None,
            'jenkins_status': self.jenkins_service.get_jenkins_status(),
            'approval_stats': self.approval_manager.get_approval_statistics(),
            'users_count': permission_service.get_users_count()
        }



