# -*- coding: utf-8 -*-
"""
用户数据模型 - 支持完整用户信息
"""

# 移除typing导入以兼容更老的Python版本


class User:
    """用户数据模型 - 完整版"""
    
    def __init__(
        self, 
        username, 
        role='用户',
        name=None,
        telegram_id=None, 
        telegram_username=None,
        projects=None,
        permissions=None,
        is_admin=False
    ):
        self.username = username
        self.role = role
        self.name = name or username
        self.telegram_id = telegram_id
        self.telegram_username = telegram_username or username
        self.projects = projects or []
        self.permissions = permissions or []
        self.is_admin = is_admin
    
    @property
    def display_name(self):
        """获取显示名称"""
        return "{}（{}）".format(self.name, self.role)
    
    @property
    def mention_name(self):
        """获取@提醒名称"""
        return "@{}".format(self.telegram_username)
    
    def has_permission(self, permission):
        """检查是否有特定权限"""
        return self.is_admin or permission in self.permissions
    
    def can_approve(self):
        """检查是否可以审批"""
        return self.has_permission('approve')
    
    def can_reject(self):
        """检查是否可以拒绝"""
        return self.has_permission('reject')
    
    def has_project_access(self, project_name):
        """检查是否有项目访问权限"""
        if self.is_admin or '*' in self.projects:
            return True
        
        # 检查项目匹配
        for proj in self.projects:
            if proj.lower() == project_name.lower() or proj in project_name or project_name in proj:
                return True
        
        return False
    
    def to_dict(self):
        """转换为字典"""
        return {
            'username': self.username,
            'name': self.name,
            'role': self.role,
            'telegram_id': self.telegram_id,
            'telegram_username': self.telegram_username,
            'projects': self.projects,
            'permissions': self.permissions,
            'is_admin': self.is_admin,
            'display_name': self.display_name,
            'mention_name': self.mention_name
        }
    
    @classmethod
    def from_dict(cls, data):
        """从字典创建实例"""
        return cls(
            username=data['username'],
            role=data.get('role', '用户'),
            name=data.get('name'),
            telegram_id=data.get('telegram_id'),
            telegram_username=data.get('telegram_username'),
            projects=data.get('projects', []),
            permissions=data.get('permissions', []),
            is_admin=data.get('is_admin', False)
        )
    
    def __str__(self):
        return self.display_name
    
    def __repr__(self):
        return f"User(username='{self.username}', name='{self.name}', role='{self.role}')"

