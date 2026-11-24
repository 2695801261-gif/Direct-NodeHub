# 大陆本地实测（Windows）

云端 GitHub Actions 不能替代你所在运营商的真实网络测试。这个脚本会在 Windows 电脑上启动官方 Mihomo，对当前仓库云端初筛通过的节点逐个建立真实代理隧道，并连续测试 3 轮。

## 使用前提

- Windows 10/11 x64 电脑。
- 电脑当前接入中国大陆本地网络（最好就是你日常使用的宽带）。
- 关闭其他 VPN、代理客户端和 Windows 系统代理；测试期间不要切换网络。
- 不需要管理员权限，不需要登录节点账号，也不需要把电脑远程交给别人。

## 操作

1. 打开仓库主页： https://github.com/2695801261-gif/Direct-NodeHub
2. 点击绿色 Code → Download ZIP，下载并解压整个仓库。
3. 在解压目录中找到 tools 文件夹。
4. 在该目录空白处打开 PowerShell，或者先打开 PowerShell 再用 cd 进入解压目录。
5. 执行：
   powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\run-mainland-probe.ps1
6. 确认电脑已处于大陆直连环境后，输入 MAINLAND。
7. 等待脚本完成。它会在桌面创建 Direct-NodeHub-Mainland 文件夹。

## 输出文件

- clash-mainland.yaml：大陆三轮实测通过、满足稳定池信誉筛选条件的订阅。
- fast-mainland.yaml：大陆三轮实测通过、达到高速门槛的订阅；不做信誉名单筛选。
- mainland-report.json：完整测试报告。把这个 JSON 发回项目讨论，才能继续核查每个节点的失败原因。

如果没有节点通过，脚本会如实生成空订阅，不会拿云端延迟冒充大陆延迟。免费公开节点可能随时失效；请勿用于支付、敏感账号或其他高风险用途。
