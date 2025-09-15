# -*- coding: utf-8 -*-
"""
配置服务模块 - 强制从配置文件读取，无硬编码默认值
"""

import os
import json
import time
import threading
from typing import Dict, Any, Optional
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from ..utils.logger import get_logger
from .config_validator import ConfigValidator, ConfigurationError

logger = get_logger(__name__)


class ConfigService:
    """配置服务 - 统一配置管理"""
    
    def __init__(self, config_dir: Optional[str] = None):
        self.config_dir = config_dir or os.path.join(os.path.dirname(__file__), '..', '..', 'config')
        self.app_config_file = os.path.join(self.config_dir, 'app.json')
        self.users_config_file = os.path.join(self.config_dir, 'users.json')
        
        # 配置缓存和锁
        self.config_cache: Dict[str, Any] = {
            'app_config': {},
            'users_config': {}, 
            'last_modified': {}
        }
        self.config_lock = threading.RLock()
        self.observer: Optional[Observer] = None
    
    def load_config_files(self) -> None:
        """加载并验证所有配置文件"""
        with self.config_lock:
            # 加载应用配置文件
            try:
                if not os.path.exists(self.app_config_file):
                    raise ConfigurationError(
                        f"❌ 应用配置文件不存在: {self.app_config_file}\n"
                        "请复制 config/app.json.example 为 config/app.json 并正确配置"
                    )
                
                with open(self.app_config_file, 'r', encoding='utf-8') as f:
                    app_config = json.load(f)
                
                # 验证应用配置
                ConfigValidator.validate_app_config(app_config)
                
                self.config_cache['app_config'] = app_config
                self.config_cache['last_modified']['app_config'] = os.path.getmtime(self.app_config_file)
                logger.info("应用配置文件已加载并验证: {}".format(self.app_config_file))
                
            except json.JSONDecodeError as e:
                error_msg = f"❌ 应用配置文件JSON格式错误: {e}"
                logger.error(error_msg)
                raise ConfigurationError(error_msg)
            except ConfigurationError:
                # 重新抛出配置错误
                raise
            except Exception as e:
                error_msg = f"❌ 加载应用配置文件失败: {e}"
                logger.error(error_msg)
                raise ConfigurationError(error_msg)
            
            # 加载用户配置文件
            try:
                if not os.path.exists(self.users_config_file):
                    raise ConfigurationError(
                        f"❌ 用户配置文件不存在: {self.users_config_file}\n"
                        "请创建 config/users.json 文件并配置用户权限"
                    )
                
                with open(self.users_config_file, 'r', encoding='utf-8') as f:
                    users_config = json.load(f)
                
                # 验证用户配置
                ConfigValidator.validate_users_config(users_config)
                
                self.config_cache['users_config'] = users_config
                self.config_cache['last_modified']['users_config'] = os.path.getmtime(self.users_config_file)
                logger.info("用户配置文件已加载并验证: {}".format(self.users_config_file))
                
            except json.JSONDecodeError as e:
                error_msg = f"❌ 用户配置文件JSON格式错误: {e}"
                logger.error(error_msg)
                raise ConfigurationError(error_msg)
            except ConfigurationError:
                # 重新抛出配置错误
                raise
            except Exception as e:
                error_msg = f"❌ 加载用户配置文件失败: {e}"
                logger.error(error_msg)
                raise ConfigurationError(error_msg)

    def get_app_config(self) -> Dict[str, Any]:
        """获取应用配置"""
        with self.config_lock:
            return self.config_cache.get('app_config', {}).copy()
    
    def get_users_config(self) -> Dict[str, str]:
        """获取用户配置"""
        with self.config_lock:
            users_config = self.config_cache.get('users_config', {})
            return users_config.get('users', {})
    
    def get_telegram_config(self) -> Dict[str, Any]:
        """获取Telegram配置 - 必须在配置文件中存在"""
        app_config = self.get_app_config()
        telegram_config = app_config.get('telegram')
        if not telegram_config:
            raise ConfigurationError(
                "❌ 配置文件中缺少 'telegram' 配置节\n"
                "请在 config/app.json 中添加 Telegram 机器人配置"
            )
        return telegram_config
    
    def get_jenkins_config(self) -> Dict[str, Any]:
        """获取Jenkins配置 - 必须在配置文件中存在"""
        app_config = self.get_app_config()
        jenkins_config = app_config.get('jenkins')
        if not jenkins_config:
            raise ConfigurationError(
                "❌ 配置文件中缺少 'jenkins' 配置节\n"
                "请在 config/app.json 中添加 Jenkins 服务器配置"
            )
        return jenkins_config
    
    def get_service_config(self) -> Dict[str, Any]:
        """获取服务配置 - 必须在配置文件中存在"""
        app_config = self.get_app_config()
        service_config = app_config.get('service')
        if not service_config:
            raise ConfigurationError(
                "❌ 配置文件中缺少 'service' 配置节\n"
                "请在 config/app.json 中添加服务配置"
            )
        return service_config
    
    def get_logging_config(self) -> Dict[str, Any]:
        """获取日志配置 - 必须在配置文件中存在"""
        app_config = self.get_app_config()
        logging_config = app_config.get('logging')
        if not logging_config:
            raise ConfigurationError(
                "❌ 配置文件中缺少 'logging' 配置节\n"
                "请在 config/app.json 中添加日志配置"
            )
        return logging_config
    
    def get_security_config(self) -> Dict[str, Any]:
        """获取安全配置 - 可选配置节"""
        app_config = self.get_app_config()
        return app_config.get('security', {})
    
    def get_features_config(self) -> Dict[str, Any]:
        """获取功能配置 - 可选配置节"""
        app_config = self.get_app_config()
        return app_config.get('features', {})
    
    def get_database_config(self) -> Dict[str, Any]:
        """获取数据库配置 - 必须在配置文件中存在"""
        app_config = self.get_app_config()
        database_config = app_config.get('database')
        if not database_config:
            raise ConfigurationError(
                "❌ 配置文件中缺少 'database' 配置节\n"
                "请在 config/app.json 中添加数据库配置"
            )
        return database_config

    def start_config_monitor(self) -> Optional[Observer]:
        """启动配置文件监控"""
        if not os.path.exists(self.config_dir):
            os.makedirs(self.config_dir)
            logger.info("创建配置目录: {}".format(self.config_dir))
        
        # 初始加载配置
        self.load_config_files()
        
        # 启动文件监控
        event_handler = ConfigFileHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, self.config_dir, recursive=False)
        self.observer.start()
        logger.info("配置文件监控已启动")
        
        return self.observer

    def stop_config_monitor(self) -> None:
        """停止配置文件监控"""
        if self.observer:
            self.observer.stop()
            logger.info("配置文件监控停止中...")


class ConfigFileHandler(FileSystemEventHandler):
    """配置文件变化处理器"""
    
    def __init__(self, config_service: ConfigService):
        self.config_service = config_service
        self.last_reload_time: Dict[str, float] = {}
    
    def on_modified(self, event):
        """文件修改事件处理"""
        if event.is_directory:
            return
            
        file_path = event.src_path
        if file_path.endswith('.json'):
            # 防止重复快速触发重载
            current_time = time.time()
            if file_path in self.last_reload_time:
                if current_time - self.last_reload_time[file_path] < 1.0:
                    return
            
            self.last_reload_time[file_path] = current_time
            file_name = os.path.basename(file_path)
            logger.info("检测到配置文件变化: {} ({})".format(file_name, file_path))
            
            # 等待文件写入完成
            time.sleep(0.5)
            
            # 触发热加载
            try:
                self.config_service.load_config_files()
                logger.info("配置文件已热加载: {}".format(file_name))
            except Exception as e:
                logger.error("配置热加载失败 ({}): {}".format(file_name, str(e)))


# 全局配置服务实例
config_service = ConfigService()
