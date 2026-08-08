# 发布流程

[English](../RELEASE.md)

1. 确认 MIT 许可证文本与包元数据一致。
2. 确认版本、变更日志、兼容性说明和迁移说明。
3. 执行 lint、format、type、65% 初始覆盖率门槛测试、构建、安装 smoke、manifest 与敏感数据检查。
4. 确认分发物不含本地状态、个人 Memory、凭据、会话 ID、机器路径、私有路由或 wake binding。
5. 每一项远程动作都必须取得明确授权。

Tag workflow 只构建分发物并上传 GitHub workflow artifact；它不会发布 PyPI，也不会创建 GitHub Release。本地构建或配置好的 workflow 不是远程 tag、注册表发布或 release 已存在的证明。

在构建分发物后，本地发布门禁包含 `python scripts/check_project.py`、`python scripts/check_sensitive_data.py` 与 `python scripts/check_dist.py`。
