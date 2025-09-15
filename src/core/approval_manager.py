# -*- coding: utf-8 -*-
"""
审批管理核心模块
"""

from typing import Dict, Optional, List, Tuple
from ..models.approval import Approval, BuildRejection
from ..services.permission_service import permission_service
from ..services.jenkins_service import JenkinsService
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ApprovalManager:
    """审批管理器 - 核心业务逻辑"""
    
    def __init__(self, jenkins_service: JenkinsService):
        self.jenkins_service = jenkins_service
        self.approval_cache: Dict[str, Approval] = {}
        self.rejected_builds_cache: Dict[str, BuildRejection] = {}
    
    def create_approval(self, job_name: str, build_number: str, environment: str, 
                       approver: Optional[str] = None, webhook_url: Optional[str] = None) -> str:
        """创建审批请求"""
        approval = Approval(
            job_name=job_name,
            build_number=build_number,
            environment=environment,
            approver=approver,
            webhook_url=webhook_url
        )
        
        approval_id = approval.approval_id
        self.approval_cache[approval_id] = approval
        
        logger.info("创建审批请求: {}".format(approval_id))
        return approval_id
    
    def get_approval(self, approval_id: str) -> Optional[Approval]:
        """获取审批对象"""
        return self.approval_cache.get(approval_id)
    
    def process_approval(self, approval_id: str, action: str, user_id: int, username: str) -> Tuple[bool, str]:
        """处理审批（同意/拒绝）"""
        try:
            # 检查审批是否存在
            approval = self.get_approval(approval_id)
            if not approval:
                return False, '审批ID不存在'
            
            # 检查审批状态
            if approval.status != 'pending':
                return False, '审批已被处理'
            
            # 权限检查
            if not self._check_permission(username):
                return False, '权限不足'
            
            # 处理审批
            if action == 'approved':
                approval.approve(user_id, username)
                self._handle_approval_success(approval)
            elif action == 'rejected':
                approval.reject(user_id, username)
                self._handle_approval_rejection(approval)
            else:
                return False, '无效的操作'
            
            logger.info("审批处理完成: {} - {} by {}".format(approval_id, action, username))
            return True, '处理成功'
            
        except Exception as e:
            logger.error("处理审批失败: {}".format(str(e)))
            return False, str(e)
    
    def _handle_approval_success(self, approval: Approval) -> None:
        """处理审批同意 - 审批通过时需要监控构建结果"""
        success = self.jenkins_service.continue_build(approval.webhook_url)
        if success:
            logger.info("Jenkins构建继续执行: {}".format(approval.approval_id))
            # 标记此审批需要接收构建结果通知
            approval.should_notify_build_result = True
            logger.info("已启用构建结果通知监控: {}".format(approval.approval_id))
        else:
            logger.warning("Jenkins构建继续执行失败: {}".format(approval.approval_id))
    
    def _handle_approval_rejection(self, approval: Approval) -> None:
        """处理审批拒绝 - 拒绝时不发送构建结果通知"""
        # 停止Jenkins构建
        success = self.jenkins_service.abort_build(approval.job_name, approval.build_number)
        if success:
            logger.info("Jenkins构建已停止: {}".format(approval.approval_id))
        
        # 记录构建拒绝
        self._record_build_rejection(approval.job_name, approval.build_number, 
                                   approval.environment, approval.processed_by)
        
        # 拒绝审批时不发送构建结果通知，直接结束流程
        logger.info("审批被拒绝，不监控构建结果: {}".format(approval.approval_id))
    
    def _record_build_rejection(self, job_name: str, build_number: str, 
                               environment: str, rejected_by: str) -> None:
        """记录构建拒绝"""
        try:
            rejection = BuildRejection(job_name, build_number, environment, rejected_by)
            
            # 保存到缓存中
            rejection_data = rejection.to_dict()
            for key in rejection.rejection_keys:
                self.rejected_builds_cache[key] = rejection_data
            
            logger.info("记录构建拒绝: {} 被 {} 拒绝".format(
                rejection.rejection_keys[0], rejected_by))
            
        except Exception as e:
            logger.error("记录构建拒绝失败: {}".format(str(e)))
    
    def is_build_rejected(self, job_name: str, build_number: str, environment: str) -> bool:
        """检查构建是否已经被拒绝过"""
        try:
            # 标准化构建号格式
            normalized_build_number = str(build_number).lstrip('#')
            
            # 检查可能的key格式
            possible_keys = [
                "{}-{}-{}".format(job_name, normalized_build_number, environment),
                "{}-#{}-{}".format(job_name, normalized_build_number, environment),
                "{}-{}-{}".format(job_name, build_number, environment)
            ]
            
            for build_key in possible_keys:
                if build_key in self.rejected_builds_cache:
                    logger.debug("找到拒绝记录: {}".format(build_key))
                    return True
            
            return False
            
        except Exception as e:
            logger.error("检查构建拒绝状态失败: {}".format(str(e)))
            return False
    
    def _check_permission(self, username: str) -> bool:
        """检查用户权限"""
        return permission_service.check_approver_permission(username)
    
    def get_approval_statistics(self) -> Dict[str, int]:
        """获取审批统计"""
        total = len(self.approval_cache)
        pending = len([a for a in self.approval_cache.values() if a.status == 'pending'])
        approved = len([a for a in self.approval_cache.values() if a.status == 'approved'])
        rejected = len([a for a in self.approval_cache.values() if a.status == 'rejected'])
        
        return {
            'total': total,
            'pending': pending,
            'approved': approved,
            'rejected': rejected
        }
    
    def get_all_approvals(self, status_filter: Optional[str] = None) -> List[Approval]:
        """获取所有审批"""
        approvals = list(self.approval_cache.values())
        
        if status_filter:
            approvals = [a for a in approvals if a.status == status_filter]
        
        # 按创建时间倒序排列
        approvals.sort(key=lambda x: x.created_timestamp, reverse=True)
        return approvals
