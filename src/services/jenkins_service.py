# -*- coding: utf-8 -*-
"""
Jenkins服务模块
"""

import requests
from typing import Dict, Any, Optional
from jenkinsapi.jenkins import Jenkins

from ..utils.logger import get_logger

logger = get_logger(__name__)


class JenkinsService:
    """Jenkins服务"""
    
    def __init__(self, jenkins_config: Dict[str, str]):
        self.jenkins_config = jenkins_config
        self._jenkins_client: Optional[Jenkins] = None
    
    @property
    def jenkins_client(self) -> Jenkins:
        """获取Jenkins客户端（懒加载）"""
        if self._jenkins_client is None:
            self._jenkins_client = Jenkins(
                self.jenkins_config['url'],
                username=self.jenkins_config['username'],
                password=self.jenkins_config['password']
            )
        return self._jenkins_client
    
    def get_jenkins_status(self) -> Dict[str, Any]:
        """获取Jenkins状态"""
        try:
            version = self.jenkins_client.get_version()
            return {
                'status': 'connected',
                'url': self.jenkins_config['url'],
                'version': version,
                'username': self.jenkins_config['username']
            }
        except Exception as e:
            logger.error("获取Jenkins状态失败: {}".format(str(e)))
            return {
                'status': 'error',
                'error': str(e),
                'url': self.jenkins_config['url']
            }
    
    def continue_build(self, webhook_url: Optional[str]) -> bool:
        """继续Jenkins构建"""
        try:
            if webhook_url:
                response = requests.post(
                    webhook_url,
                    json={'action': 'proceed'},
                    timeout=10
                )
                logger.info("Jenkins webhook调用结果: {}".format(response.status_code))
                return response.status_code == 200
            else:
                logger.warning("未提供webhook_url，无法继续构建")
                return False
        except Exception as e:
            logger.error("继续Jenkins构建失败: {}".format(str(e)))
            return False
    
    def abort_build(self, job_name: str, build_number: str) -> bool:
        """中止Jenkins构建"""
        try:
            job = self.jenkins_client.get_job(job_name)
            build = job.get_build(int(build_number))
            
            if build.is_running():
                build.stop()
                logger.info("Jenkins构建已停止: {}#{}".format(job_name, build_number))
                return True
            else:
                logger.info("Jenkins构建已经停止: {}#{}".format(job_name, build_number))
                return True
                
        except Exception as e:
            logger.error("停止Jenkins构建失败: {}".format(str(e)))
            return False
    
    def get_build_logs(self, job_name: str, build_number: str) -> Dict[str, Any]:
        """获取Jenkins构建日志"""
        try:
            # 使用jenkinsapi获取构建日志
            job = self.jenkins_client.get_job(job_name)
            build = job.get_build(int(build_number))
            
            # 获取完整日志
            console_output = build.get_console()
            
            # 获取构建信息
            build_info = {
                'job_name': job_name,
                'build_number': build_number,
                'status': build.get_status(),
                'duration': build.get_duration().total_seconds() if build.get_duration() else 0,
                'started_at': build.get_timestamp().strftime('%Y-%m-%d %H:%M:%S'),
                'url': build.get_build_url(),
                'console_url': f"{build.get_build_url()}console",
                'logs': console_output,
                'is_running': build.is_running()
            }
            
            logger.info(f"获取Jenkins日志成功: {job_name}#{build_number}")
            return build_info
            
        except Exception as e:
            logger.error(f"获取Jenkins日志失败: {str(e)}")
            return {
                'job_name': job_name,
                'build_number': build_number,
                'status': 'UNKNOWN',
                'error': str(e),
                'logs': f"日志获取失败: {str(e)}"
            }