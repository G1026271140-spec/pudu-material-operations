# 全球之旅素材自动整理

这个本地自动化使用“营销物料管理系统”飞书应用的凭据，监控指定多维表格。安装后的新记录只要“素材提交（压缩包）”不为空，就会：

1. 下载附件到桌面 `全球之旅整理素材`。
2. 使用 7-Zip 自动解压 ZIP、RAR 和 7z，并限制异常大的解压内容。
3. 按扩展名识别图片与视频。
4. 图片写入 `原始素材（图片）`，视频写入 `原始素材（视频）`。
5. 在 `state/processed.json` 保存状态，避免重复上传。
6. 图片和视频成功回写飞书后，自动删除本地 ZIP、RAR 或 7z 压缩包；解压后的素材保留。

飞书云端自动化无法直接写入个人电脑桌面，因此这里使用 Windows 登录后常驻的计划任务，每 4 小时检查一次新附件。
后台任务和 7-Zip 解压均以无窗口模式运行，不会弹出或闪烁控制台窗口。

## 安装

    .\install_automation_task.ps1

安装脚本会先检查飞书访问权限，再把当前已有附件建立为历史基线，因此不会重新处理表格里的旧压缩包。

## 手动检查

    C:\Users\gaohongyuan1\Desktop\营销物料管理系统\.venv\Scripts\python.exe material_automation.py --check
    C:\Users\gaohongyuan1\Desktop\营销物料管理系统\.venv\Scripts\python.exe material_automation.py --once

日志位于 `logs/worker.log`，下载目录位于 `C:\Users\gaohongyuan1\Desktop\全球之旅整理素材`。

## 卸载

    .\uninstall_automation_task.ps1

卸载不会删除已经下载的素材和本地状态文件。
