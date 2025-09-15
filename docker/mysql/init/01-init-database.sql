-- Jenkins审批机器人数据库初始化脚本
-- 创建时间: 2024-01-01
-- 版本: 1.0.0

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- 使用数据库
USE jenkins_approval;

-- 创建审批表
CREATE TABLE IF NOT EXISTS `approvals` (
  `request_id` VARCHAR(255) PRIMARY KEY COMMENT '审批请求ID',
  `project` VARCHAR(100) NOT NULL COMMENT '项目名称',
  `env` VARCHAR(50) NOT NULL COMMENT '环境',
  `build` VARCHAR(100) NOT NULL COMMENT '构建号',
  `job` VARCHAR(200) NOT NULL COMMENT '任务名称',
  `version` VARCHAR(100) NOT NULL COMMENT '版本号',
  `desc` TEXT COMMENT '描述',
  `action` VARCHAR(50) COMMENT '操作类型',
  `timeout_seconds` INT DEFAULT 1800 COMMENT '超时时间(秒)',
  `status` VARCHAR(20) DEFAULT 'pending' COMMENT '状态: pending/approved/rejected/timeout',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `approver` VARCHAR(100) COMMENT '审批人',
  `approver_role` VARCHAR(100) COMMENT '审批人角色',
  `comment` TEXT COMMENT '审批备注',
  `is_locked` TINYINT(1) DEFAULT 0 COMMENT '是否锁定',
  `lock_timestamp` DATETIME COMMENT '锁定时间',
  `lock_timeout` INT DEFAULT 60 COMMENT '锁定超时(秒)',
  
  INDEX `idx_status` (`status`),
  INDEX `idx_created_at` (`created_at`),
  INDEX `idx_project_env` (`project`, `env`),
  INDEX `idx_approver` (`approver`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审批请求表';

-- 创建审批历史表
CREATE TABLE IF NOT EXISTS `approval_history` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
  `request_id` VARCHAR(255) NOT NULL COMMENT '审批请求ID',
  `action` VARCHAR(50) NOT NULL COMMENT '操作: created/approved/rejected/timeout',
  `operator` VARCHAR(100) NOT NULL COMMENT '操作人',
  `operator_role` VARCHAR(100) COMMENT '操作人角色',
  `comment` TEXT COMMENT '操作备注',
  `timestamp` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '操作时间',
  
  INDEX `idx_request_id` (`request_id`),
  INDEX `idx_timestamp` (`timestamp`),
  INDEX `idx_operator` (`operator`),
  
  FOREIGN KEY (`request_id`) REFERENCES `approvals` (`request_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审批历史表';

-- 创建用户会话表（可选）
CREATE TABLE IF NOT EXISTS `user_sessions` (
  `session_id` VARCHAR(255) PRIMARY KEY COMMENT '会话ID',
  `user_id` VARCHAR(100) NOT NULL COMMENT '用户ID',
  `username` VARCHAR(100) NOT NULL COMMENT '用户名',
  `telegram_id` BIGINT COMMENT 'Telegram用户ID',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `expires_at` DATETIME NOT NULL COMMENT '过期时间',
  `last_activity` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '最后活动时间',
  
  INDEX `idx_user_id` (`user_id`),
  INDEX `idx_expires_at` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户会话表';

-- 创建构建日志表（可选）
CREATE TABLE IF NOT EXISTS `build_logs` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
  `request_id` VARCHAR(255) NOT NULL COMMENT '审批请求ID',
  `job_name` VARCHAR(200) NOT NULL COMMENT '任务名称',
  `build_number` VARCHAR(100) NOT NULL COMMENT '构建号',
  `status` VARCHAR(50) NOT NULL COMMENT '构建状态',
  `start_time` DATETIME COMMENT '开始时间',
  `end_time` DATETIME COMMENT '结束时间',
  `duration` INT COMMENT '持续时间(秒)',
  `logs` LONGTEXT COMMENT '构建日志',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  
  INDEX `idx_request_id` (`request_id`),
  INDEX `idx_job_build` (`job_name`, `build_number`),
  INDEX `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='构建日志表';

-- 插入测试数据
INSERT IGNORE INTO `approvals` (
  `request_id`, `project`, `env`, `build`, `job`, `version`, `desc`, `action`, `status`
) VALUES 
(
  'webapp-001-prod', 'webapp', 'prod', '001', 'webapp-deploy', 
  'v1.0.0', '生产环境首次部署', '部署', 'pending'
),
(
  'api-002-test', 'api', 'test', '002', 'api-deploy', 
  'v1.1.0', '测试环境版本更新', '部署', 'approved'
),
(
  'frontend-003-prod', 'frontend', 'prod', '003', 'frontend-deploy', 
  'v2.0.0', '前端重构版本发布', '部署', 'rejected'
);

-- 插入历史记录
INSERT IGNORE INTO `approval_history` (
  `request_id`, `action`, `operator`, `operator_role`, `comment`
) VALUES 
('webapp-001-prod', 'created', 'system', 'system', '系统创建审批请求'),
('api-002-test', 'created', 'system', 'system', '系统创建审批请求'),
('api-002-test', 'approved', 'RipenWang', '运维工程师', '测试环境审批通过'),
('frontend-003-prod', 'created', 'system', 'system', '系统创建审批请求'),
('frontend-003-prod', 'rejected', 'ProjectManager', '项目经理', '版本不稳定，暂缓发布');

SET FOREIGN_KEY_CHECKS = 1;

-- 显示表结构
SHOW TABLES;
DESCRIBE approvals;
DESCRIBE approval_history;

-- 显示初始数据
SELECT COUNT(*) as approval_count FROM approvals;
SELECT COUNT(*) as history_count FROM approval_history;

SHOW ENGINE INNODB STATUS\G

-- 完成提示
SELECT '✅ Jenkins审批机器人数据库初始化完成！' as message;
