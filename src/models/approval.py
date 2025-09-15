# -*- coding: utf-8 -*-
"""
审批数据模型
"""

import time
from datetime import datetime
from typing import Optional, Dict, Any


class Approval:
    """审批数据模型"""
    
    def __init__(self, job_name: str, build_number: str, environment: str, 
                 approver: Optional[str] = None, webhook_url: Optional[str] = None):
        self.job_name = job_name
        self.build_number = build_number
        self.environment = environment
        self.approver = approver
        self.webhook_url = webhook_url
        self.status = 'pending'
        self.created_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.created_timestamp = time.time()
        self.processed_by: Optional[str] = None
        self.processed_at: Optional[str] = None
        self.processor_user_id: Optional[int] = None
        self.should_notify_build_result: bool = False  # 是否需要构建结果通知
    
    @property
    def approval_id(self) -> str:
        """生成审批ID"""
        return "{}-{}-{}".format(self.job_name, self.build_number, self.environment)
    
    def approve(self, user_id: int, username: str) -> None:
        """标记为已同意"""
        self.status = 'approved'
        self.processed_by = username
        self.processed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.processor_user_id = user_id
    
    def reject(self, user_id: int, username: str) -> None:
        """标记为已拒绝"""
        self.status = 'rejected'
        self.processed_by = username
        self.processed_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.processor_user_id = user_id
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'job_name': self.job_name,
            'build_number': self.build_number,
            'environment': self.environment,
            'approver': self.approver,
            'webhook_url': self.webhook_url,
            'status': self.status,
            'created_at': self.created_at,
            'created_timestamp': self.created_timestamp,
            'processed_by': self.processed_by,
            'processed_at': self.processed_at,
            'processor_user_id': self.processor_user_id
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Approval':
        """从字典创建实例"""
        approval = cls(
            job_name=data['job_name'],
            build_number=data['build_number'],
            environment=data['environment'],
            approver=data.get('approver'),
            webhook_url=data.get('webhook_url')
        )
        approval.status = data.get('status', 'pending')
        approval.created_at = data.get('created_at', approval.created_at)
        approval.created_timestamp = data.get('created_timestamp', approval.created_timestamp)
        approval.processed_by = data.get('processed_by')
        approval.processed_at = data.get('processed_at')
        approval.processor_user_id = data.get('processor_user_id')
        return approval


class BuildRejection:
    """构建拒绝记录模型"""
    
    def __init__(self, job_name: str, build_number: str, environment: str, rejected_by: str):
        self.job_name = job_name
        self.build_number = build_number
        self.environment = environment
        self.rejected_by = rejected_by
        self.rejected_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        self.rejected_timestamp = time.time()
    
    @property
    def rejection_keys(self) -> list:
        """生成可能的拒绝key列表"""
        normalized_build_number = str(self.build_number).lstrip('#')
        return [
            "{}-{}-{}".format(self.job_name, normalized_build_number, self.environment),
            "{}-#{}-{}".format(self.job_name, normalized_build_number, self.environment)
        ]
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'job_name': self.job_name,
            'build_number': self.build_number,
            'environment': self.environment,
            'rejected_by': self.rejected_by,
            'rejected_at': self.rejected_at,
            'rejected_timestamp': self.rejected_timestamp
        }
