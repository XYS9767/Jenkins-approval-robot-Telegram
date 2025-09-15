# -*- coding: utf-8 -*-
"""
配置验证器模块 - 确保所有必需的配置项存在
"""

from typing import Dict, Any, List
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ConfigurationError(Exception):
    """配置错误异常"""
    def __init__(self, message: str, missing_keys: List[str] = None):
        super().__init__(message)
        self.missing_keys = missing_keys or []


class ConfigValidator:
    """配置验证器 - 验证配置文件的完整性"""
    
    # 必需的配置项结构
    REQUIRED_CONFIG_STRUCTURE = {
        'telegram': {
            'required_keys': ['bot_token', 'chat_id'],
            'optional_keys': ['proxy']
        },
        'jenkins': {
            'required_keys': ['url', 'username', 'password'],
            'optional_keys': ['api_timeout']
        },
        'service': {
            'required_keys': ['host', 'port'],
            'optional_keys': ['debug']
        },
        'database': {
            'required_keys': ['type', 'mysql'],
            'optional_keys': ['connection_timeout', 'auto_cleanup_days', 'backup']
        },
        'logging': {
            'required_keys': ['level', 'file_path'],
            'optional_keys': []
        }
    }
    
    REQUIRED_DATABASE_MYSQL_KEYS = ['host', 'port', 'database', 'username', 'password']
    REQUIRED_USERS_KEYS = ['users']
    
    @classmethod
    def validate_app_config(cls, config: Dict[str, Any]) -> None:
        """验证应用配置文件"""
        if not config:
            raise ConfigurationError(
                "❌ 应用配置文件为空或无法读取，请检查 config/app.json 文件",
                missing_keys=['config/app.json']
            )
        
        missing_sections = []
        missing_keys = []
        
        # 验证顶级配置节
        for section_name, section_config in cls.REQUIRED_CONFIG_STRUCTURE.items():
            if section_name not in config:
                missing_sections.append(section_name)
                continue
            
            section_data = config[section_name]
            if not isinstance(section_data, dict):
                missing_sections.append(f"{section_name} (应该是对象)")
                continue
            
            # 验证必需的键
            for required_key in section_config['required_keys']:
                if required_key not in section_data:
                    missing_keys.append(f"{section_name}.{required_key}")
        
        # 特殊验证数据库MySQL配置
        if 'database' in config and 'mysql' in config['database']:
            mysql_config = config['database']['mysql']
            for required_key in cls.REQUIRED_DATABASE_MYSQL_KEYS:
                if required_key not in mysql_config:
                    missing_keys.append(f"database.mysql.{required_key}")
        
        # 如果有缺失的配置，抛出异常
        if missing_sections or missing_keys:
            error_message = "❌ 配置文件缺少必需的配置项:\n"
            if missing_sections:
                error_message += f"缺少配置节: {', '.join(missing_sections)}\n"
            if missing_keys:
                error_message += f"缺少配置键: {', '.join(missing_keys)}\n"
            error_message += "\n请参考 config/app.json.example 或安装文档完整配置"
            
            raise ConfigurationError(error_message, missing_keys=missing_sections + missing_keys)
        
        # 验证关键配置项的值
        cls._validate_config_values(config)
        
        logger.info("✅ 应用配置验证通过")
    
    @classmethod
    def validate_users_config(cls, config: Dict[str, Any]) -> None:
        """验证用户配置文件"""
        if not config:
            raise ConfigurationError(
                "❌ 用户配置文件为空或无法读取，请检查 config/users.json 文件",
                missing_keys=['config/users.json']
            )
        
        missing_keys = []
        
        # 验证必需的键
        for required_key in cls.REQUIRED_USERS_KEYS:
            if required_key not in config:
                missing_keys.append(required_key)
        
        # 验证users结构
        if 'users' in config:
            users = config['users']
            if not isinstance(users, dict) or len(users) == 0:
                missing_keys.append("users (应该包含至少一个用户)")
        
        if missing_keys:
            error_message = f"❌ 用户配置文件缺少必需的配置项: {', '.join(missing_keys)}\n"
            error_message += "请参考 config/users.json 示例文件或安装文档"
            
            raise ConfigurationError(error_message, missing_keys=missing_keys)
        
        logger.info("✅ 用户配置验证通过")
    
    @classmethod
    def _validate_config_values(cls, config: Dict[str, Any]) -> None:
        """验证配置值的有效性"""
        
        # 验证Telegram配置
        telegram_config = config.get('telegram', {})
        if 'bot_token' in telegram_config:
            bot_token = telegram_config['bot_token']
            if not bot_token or not isinstance(bot_token, str) or ':' not in bot_token:
                raise ConfigurationError("❌ Telegram bot_token 格式无效，应该类似: '1234567890:ABCDEFghijklmnop...'")
        
        if 'chat_id' in telegram_config:
            chat_id = telegram_config['chat_id']
            if not chat_id or not isinstance(chat_id, str):
                raise ConfigurationError("❌ Telegram chat_id 不能为空")
        
        # 验证Jenkins配置
        jenkins_config = config.get('jenkins', {})
        if 'url' in jenkins_config:
            jenkins_url = jenkins_config['url']
            if not jenkins_url or not isinstance(jenkins_url, str) or not jenkins_url.startswith('http'):
                raise ConfigurationError("❌ Jenkins URL 格式无效，应该以 http:// 或 https:// 开头")
        
        # 验证数据库配置
        database_config = config.get('database', {})
        if 'mysql' in database_config:
            mysql_config = database_config['mysql']
            if 'port' in mysql_config:
                port = mysql_config['port']
                if not isinstance(port, int) or port <= 0 or port > 65535:
                    raise ConfigurationError("❌ 数据库端口号无效，应该是 1-65535 之间的整数")
        
        # 验证服务配置
        service_config = config.get('service', {})
        if 'port' in service_config:
            port = service_config['port']
            if not isinstance(port, int) or port <= 0 or port > 65535:
                raise ConfigurationError("❌ 服务端口号无效，应该是 1-65535 之间的整数")
    
    @classmethod
    def get_missing_config_template(cls, missing_keys: List[str]) -> str:
        """根据缺失的配置项生成配置模板"""
        template = "# 缺失的配置项模板\n"
        template += "# 请将以下内容添加到对应的配置文件中\n\n"
        
        for key in missing_keys:
            if key.startswith('telegram.'):
                template += cls._get_telegram_template()
            elif key.startswith('jenkins.'):
                template += cls._get_jenkins_template()
            elif key.startswith('database.'):
                template += cls._get_database_template()
            elif key.startswith('service.'):
                template += cls._get_service_template()
            elif key.startswith('logging.'):
                template += cls._get_logging_template()
        
        return template
    
    @classmethod
    def _get_telegram_template(cls) -> str:
        return '''
"telegram": {
  "bot_token": "YOUR_BOT_TOKEN_HERE",
  "chat_id": "YOUR_CHAT_ID_HERE",
  "proxy": {
    "enabled": false,
    "url": "http://proxy-server:port"
  }
}
'''
    
    @classmethod
    def _get_jenkins_template(cls) -> str:
        return '''
"jenkins": {
  "url": "http://your-jenkins-server:8080",
  "username": "admin",
  "password": "your_password_or_token",
  "api_timeout": 30
}
'''
    
    @classmethod
    def _get_database_template(cls) -> str:
        return '''
"database": {
  "type": "mysql",
  "mysql": {
    "host": "localhost",
    "port": 3306,
    "database": "jenkins_approval",
    "username": "jenkins_user",
    "password": "jenkins_password_2024",
    "charset": "utf8mb4"
  },
  "connection_timeout": 30,
  "auto_cleanup_days": 30
}
'''
    
    @classmethod
    def _get_service_template(cls) -> str:
        return '''
"service": {
  "host": "0.0.0.0",
  "port": 8770,
  "debug": false
}
'''
    
    @classmethod
    def _get_logging_template(cls) -> str:
        return '''
"logging": {
  "level": "INFO",
  "file_path": "logs/app.log"
}
'''
