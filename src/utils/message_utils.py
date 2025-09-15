# -*- coding: utf-8 -*-
"""
消息处理工具模块
"""

import re
from typing import Optional


def clean_message_text(text: Optional[str]) -> str:
    """清理消息文本，确保正确处理中文字符"""
    try:
        # 确保输入是有效的字符串
        if text is None:
            return "空消息"
        
        if not isinstance(text, str):
            try:
                text = str(text)
            except:
                return "消息转换失败"
        
        # 确保字符串是UTF-8编码
        if isinstance(text, bytes):
            try:
                text = text.decode('utf-8', errors='replace')
            except:
                text = text.decode('utf-8', errors='ignore')
        
        # 移除有害的控制字符，保留中文和其他Unicode字符
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        
        # 压缩多余的空白，但保持基本格式
        text = re.sub(r' {3,}', '  ', text)  # 将3个以上连续空格压缩为2个
        text = re.sub(r'\n{3,}', '\n\n', text)  # 将3个以上连续换行压缩为2个
        text = re.sub(r'\t{2,}', '\t', text)  # 将多个制表符压缩为1个
        
        # 清理首尾空白
        text = text.strip()
        
        # 确保消息不为空
        if not text:
            return "空消息"
            
        return text
        
    except Exception:
        # 最保守的处理：直接返回原始文本（如果可能）
        try:
            if isinstance(text, str) and text.strip():
                return text.strip()
            elif text is not None:
                return str(text).strip() if str(text).strip() else "消息处理异常"
            else:
                return "空消息"
        except:
            return "消息处理异常"


def format_approval_message(approval_data: dict) -> str:
    """格式化审批消息"""
    env_text = "生产环境" if approval_data['environment'] == 'production' else "测试环境"
    env_icon = "[PROD]" if approval_data['environment'] == 'production' else "[TEST]"
    
    return """Jenkins 发布审批

项目: {}
{} 环境: {}
构建: #{}
时间: {}

请审批""".format(
        approval_data['job_name'],
        env_icon,
        env_text,
        approval_data['build_number'],
        approval_data['created_at']
    )


def format_approval_result_message(approval_data: dict, action: str, username: str, timestamp: str) -> str:
    """格式化审批结果消息"""
    if action == 'approved':
        return """[APPROVED] 审批处理完成

状态: 同意发布
项目: {}
构建: #{}
环境: {}
处理人: {}
时间: {}

构建继续执行""".format(
            approval_data['job_name'],
            approval_data['build_number'],
            approval_data['environment'],
            username,
            timestamp
        )
    else:
        return """[REJECTED] 审批已拒绝

项目: {}
构建: #{}
处理人: {}
时间: {}

构建已终止""".format(
            approval_data['job_name'],
            approval_data['build_number'],
            username,
            timestamp
        )


def format_notification_message(message_type: str, message: str) -> str:
    """格式化通知消息"""
    emoji = '✅' if message_type == 'success' else '❌' if message_type == 'failure' else '📢'
    title = '部署成功' if message_type == 'success' else '部署失败' if message_type == 'failure' else '通知'
    return "{} {}\n\n{}".format(emoji, title, message)
