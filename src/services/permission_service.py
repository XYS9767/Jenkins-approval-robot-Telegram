# -*- coding: utf-8 -*-
"""
权限服务模块 - 支持完整用户配置结构，强制从配置文件读取
"""

import json
import os
from ..models.user import User
from ..utils.logger import get_logger
from .config_validator import ConfigurationError

logger = get_logger(__name__)


class PermissionService:
    """权限服务 - 支持完整的用户配置和项目映射"""
    
    def __init__(self):
        self.users_config = {}  # Dict
        self.project_mapping = {}  # Dict
        self.settings = {}  # Dict
        self._users_cache = {}  # Dict[str, User]
        self.config_file_path = os.path.join(os.path.dirname(__file__), '../../config/users.json')
    
    def load_users(self):
        """加载用户配置 - 支持简洁格式"""
        try:
            if os.path.exists(self.config_file_path):
                with open(self.config_file_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    
                self.users_config = config.get('users', {})
                
                # 支持简洁格式和复杂格式 - 不使用硬编码默认值
                self.project_mapping = config.get('project_mapping', {})
                self.settings = config.get('settings', {})
                
                # 更新用户缓存
                self._users_cache.clear()
                for username, user_data in self.users_config.items():
                    if isinstance(user_data, dict):
                        # 复杂格式：完整的用户信息
                        self._users_cache[username] = User(
                            username=username, 
                            role=user_data.get('role', '用户'),
                            name=user_data.get('name', username),
                            telegram_id=user_data.get('telegram_id'),
                            telegram_username=user_data.get('telegram_username', username),
                            projects=user_data.get('projects', []),
                            permissions=user_data.get('permissions', ['approve', 'reject']),
                            is_admin=user_data.get('is_admin', False)
                        )
                    else:
                        # 简洁格式：用户名 -> 角色
                        role = str(user_data)
                        is_admin = '运维' in role or 'admin' in role.lower()
                        self._users_cache[username] = User(
                            username=username, 
                            role=role,
                            name=username,
                            telegram_username=username,
                            projects=self._get_default_user_projects(username, role),
                            permissions=['approve', 'reject'],
                            is_admin=is_admin
                        )
                
                logger.info("用户权限配置已加载，共{}个用户".format(len(self.users_config)))
            else:
                logger.warning("用户配置文件不存在: {}".format(self.config_file_path))
                self.users_config = {}
                self.project_mapping = {}
                self.settings = {}
                
        except Exception as e:
            logger.error("加载用户配置失败: {}".format(e))
            self.users_config = {}
            self.project_mapping = {}
            self.settings = {}
            self._users_cache.clear()
    
    def _get_default_user_projects(self, username, role):
        """为简洁格式的用户获取默认项目列表"""
        try:
            # 管理员角色有所有项目权限
            if '运维' in role or 'admin' in role.lower() or '管理' in role:
                return ['*']
            
            # 从项目映射中查找用户所属的项目
            user_projects = []
            for project, owners in self.project_mapping.items():
                if project != 'default' and username in owners:
                    user_projects.append(project)
            
            # 如果没有找到特定项目，返回空列表（需要明确配置）
            return user_projects if user_projects else []
            
        except Exception as e:
            logger.error("获取默认用户项目失败: {}".format(e))
            return []
    
    def get_approval_settings(self):
        """获取审批设置 - 从配置文件读取或使用合理的默认值"""
        # 提供必要的默认值，但建议在配置文件中明确指定
        default_settings = {
            'approval_timeout_minutes': 30,
            'reminder_interval_minutes': 5,
            'max_reminders': 6,
            'auto_reject_on_timeout': False
        }
        
        # 合并配置文件中的设置和默认设置
        merged_settings = default_settings.copy()
        if self.settings:
            merged_settings.update(self.settings)
        
        return merged_settings
    
    def get_project_owners(self, project_name):
        """获取项目负责人列表"""
        try:
            if not self.project_mapping:
                self.load_users()
            
            # 直接查找项目映射
            if project_name in self.project_mapping:
                return self.project_mapping[project_name]
            
            # 模糊匹配
            for proj_key, owners in self.project_mapping.items():
                if proj_key.lower() in project_name.lower() or project_name.lower() in proj_key.lower():
                    return owners
            
            # 使用默认负责人
            return self.project_mapping.get('default', list(self.users_config.keys())[:2])
            
        except Exception as e:
            logger.error("获取项目负责人失败: {}".format(e))
            return list(self.users_config.keys())[:2] if self.users_config else []
    
    def get_user_info(self, username):
        """获取完整用户信息 - 支持简洁格式"""
        try:
            if not self.users_config:
                self.load_users()
            
            user_data = self.users_config.get(username)
            if isinstance(user_data, dict):
                # 复杂格式，直接返回
                return user_data
            elif user_data:
                # 简洁格式，构建完整信息
                role = str(user_data)
                return {
                    'name': username,
                    'role': role,
                    'telegram_username': username,
                    'telegram_id': None,
                    'projects': self._get_default_user_projects(username, role),
                    'permissions': ['approve', 'reject'],
                    'is_admin': '运维' in role or 'admin' in role.lower()
                }
            return None
        except Exception as e:
            logger.error("获取用户信息失败: {}".format(e))
            return None
    
    def get_user_display_name(self, username):
        """获取用户显示名称（含角色）"""
        user_info = self.get_user_info(username)
        if user_info:
            name = user_info.get('name', username)
            role = user_info.get('role', '用户')
            return f"{name}（{role}）"
        return username
    
    def get_telegram_mentions(self, usernames):
        """生成Telegram @提醒字符串"""
        mentions = []
        for username in usernames:
            user_info = self.get_user_info(username)
            if user_info and user_info.get('telegram_username'):
                mentions.append(f"@{user_info['telegram_username']}")
            else:
                mentions.append(f"@{username}")
        return " ".join(mentions)
    
    def check_permission(self, username, permission=None):
        """检查用户是否有指定权限"""
        try:
            user_info = self.get_user_info(username)
            if not user_info:
                return False
            
            if permission is None:
                return True  # 用户存在即有基本权限
            
            # 检查具体权限
            permissions = user_info.get('permissions', [])
            return permission in permissions or user_info.get('is_admin', False)
            
        except Exception as e:
            logger.error("权限检查失败: {}".format(e))
            return False
    
    def check_project_permission(self, username, project_name):
        """检查用户对项目的权限"""
        try:
            user_info = self.get_user_info(username)
            if not user_info:
                return False
            
            if user_info.get('is_admin', False):
                return True
            
            projects = user_info.get('projects', [])
            if '*' in projects:
                return True
            
            # 检查项目匹配
            for proj in projects:
                if proj.lower() == project_name.lower() or proj in project_name or project_name in proj:
                    return True
            
            return False
            
        except Exception as e:
            logger.error("项目权限检查失败: {}".format(e))
            return False
    
    
    def get_user(self, username):
        """获取用户对象"""
        if not self._users_cache:
            self.load_users()
        return self._users_cache.get(username)
    
    def get_all_users(self):
        """获取所有用户"""
        if not self._users_cache:
            self.load_users()
        return list(self._users_cache.values())
    
    def get_users_count(self):
        """获取用户数量"""
        return len(self.users_config)
    
    def check_approver_permission(self, username):
        """检查用户是否有审批权限"""
        return self.check_permission(username, 'approve')
    
    def get_user_role(self, username):
        """获取用户角色"""
        user_info = self.get_user_info(username)
        return user_info.get('role', '用户') if user_info else '用户'


# 全局权限服务实例
permission_service = PermissionService()


