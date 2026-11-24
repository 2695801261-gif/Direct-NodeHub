# Direct-NodeHub

面向中国大陆网络环境的公开代理节点筛选与订阅项目。

> **安全提示：** 本项目采集的节点来自公开互联网，运营者身份与日志政策通常不可验证。请勿通过免费公开节点访问银行、支付、主邮箱、工作账号或其他敏感服务。项目的风险筛选只能降低已知风险，不能保证节点绝对安全或 IP 绝对干净。

## 项目目标

- 自动发现公开代理节点，并进行协议/连通性验证。
- 将云端探测结果与中国大陆用户实测结果分开记录；境外 CI 延迟不代表大陆网络延迟。
- 对命中高风险情报、明确滥用记录或无法完成必要核验的节点拒绝发布或隔离。
- 生成 Mihomo / Clash Meta 可导入的稳定节点、高速节点订阅，以及家宽链式代理模板和静态状态页。
- 定时更新，并支持手动触发。

## 发布原则

1. 只有通过协议解析、连接验证和出口验证的节点才有资格进入候选池。
2. 高风险或证据冲突的节点不进入正式订阅。
3. 速度与稳定性指标必须注明测试位置和时间。
4. 不承诺住宅 IP、零风险、永久可用或大陆全网稳定。
5. 免费公开节点随时可能失效，使用者需自行评估风险。

## 两级测试设计

### 第一级：云端预筛

GitHub Actions 自动检查候选节点的 TCP 端口是否可达，并记录云端探测耗时。此结果仅代表 GitHub 托管运行器所在网络的 TCP 可达性，不代表代理握手成功、代理隧道可用、速度合格或中国大陆可连接。

### 第二级：中国大陆实测

大陆测试报告使用 `reports/mainland/` 保存，必须明确标记 `probe_location: mainland_china`。云端工作流不会生成或伪造大陆测试结果。只有经过大陆网络实际测试的节点，才能获得中国大陆可用确认。

当前阶段不会把 TCP 端口开放等同于节点可用，也不会把未测试节点放入正式订阅。

## 当前状态

已实现：
- 多源采集与 URI / Clash-Mihomo YAML 解析，单源候选数量受策略限制，并保留跨来源命中记录。
- 云端 TCP 可达性预筛。
- 使用官方 Mihomo 稳定版对节点配置进行校验，启动真实代理隧道，并通过多个 HTTPS 出口查询服务核对出口 IP。
- 对通过协议验证的节点进行 3 轮重复连接、出口 IP 一致性、延迟和双向速度测试；云端稳定池要求 3/3 成功、出口 IP 一致、至少两个出口查询成功、中位云端延迟不高于 1000 ms、下载至少 128 KiB/s、上传至少 32 KiB/s。高速池额外要求下载至少 512 KiB/s、上传至少 128 KiB/s。云端延迟不能当作大陆延迟。
- 生成 `public/clash.yaml`（风险情报筛选稳定池）、`public/fast.yaml`（高速稳定池）、`public/chain-template.yaml`（公开节点作为前置、用户自有家宽端点作为最终出口）、`public/status.json` 和 `public/index.html`。
- 每 6 小时由 GitHub Actions 自动更新，并可手动触发。
- 下载 IPsum 与 Tor 出口列表进行已知风险命中筛查；IPsum 仅采用至少 3 个情报源同时命中的地址。
- 大陆实测报告格式校验；云端任务不会伪造大陆探测结果。

当前采集源包括 V2RayAggregator、NoMoreWalls、v2rayfree、learnLi/free-nodes、735754647/Free-Nodes、zhuhaiuk/free-nodes、a2470982985/getNode、rtwo2/FastNodes、morpheusadam/v2ray-config、Pawdroid/Free-servers、snakem982/proxypool 等。来源会失效或更改格式，运行结果会记录成功/失败状态；不会假定每个源每次都能返回节点。

风险状态的含义：
- `blocked`：命中已知风险情报或出口 IP 非公网地址，拒绝进入候选池。
- `unconfirmed`：未命中当前威胁情报，但这不等于干净 IP；只允许进入独立的未确认观察池。
- `unknown`：没有有效出口 IP 或威胁情报源不可用，隔离处理。

**验收边界：** 云端自动流程已接入协议验证、风险筛查、重复稳定性测试、订阅生成与静态状态页。每轮运行仍需查看 Actions 的实际结果；大陆网络实际探测仍需要真实大陆网络作为探测点，云端成功不等于大陆可用。

## 计划输出

- `public/clash.yaml`：Mihomo / Clash Meta 订阅
- `public/status.json`：节点数量、更新时间和测试边界
- `public/index.html`：静态状态页面

## 免责声明

本项目仅用于网络技术研究与个人测试。使用者应遵守所在地法律法规及节点来源平台的服务条款。项目维护者不控制第三方节点，也不对其可用性、隐私政策或行为作保证。


## 链式代理模板说明

- 模板采用 Mihomo 的 `dialer-proxy`：公开节点组 `ENTRY-AUTO` 作为前置，用户自己的家宽 SOCKS5 节点作为最终出口。
- 将模板中的 `YOUR_HOME_HOST`、端口、用户名和密码在本地替换为自己的家宽服务信息；不要把真实凭据提交到公开仓库。
- 最终访问网站看到的是家宽出口 IP。若家宽端点本身不可从前置节点访问、家中路由/NAT/防火墙不通，链式配置无法自动修复这些问题。
- Mihomo 的 `dialer-proxy` 官方说明见 https://wiki.metacubex.one/en/config/proxies/dialer-proxy/ 。

## 可选：中国大陆本地实测

云端运行器不能代替大陆网络。若要确认节点能否从你的大陆宽带/移动网络实际使用，可在 Windows 电脑上下载仓库和官方 Mihomo Windows 版，安装 Python 3.12 并运行：

```powershell
python -m pip install -r requirements.txt
$env:MIHOMO_BIN="C:\工具\mihomo.exe"
python -m direct_nodehub.mainland_probe --confirm-mainland --limit 20 --rounds 3
```

运行时必须确实处于中国大陆网络，并关闭其他 VPN/代理；只有明确确认后脚本才会生成 reports/mainland/ 报告。报告包含节点 ID、三轮连通情况、出口 IP、下载和上传速度。现在也提供 Windows 一键脚本：在已解压的仓库目录打开 PowerShell，运行 `Set-ExecutionPolicy -Scope Process Bypass`，再运行 `.	oolsun-mainland-probe.ps1`。脚本会安装项目依赖、下载并校验官方 Mihomo Windows 版，然后要求你输入 `MAINLAND` 确认当前已关闭 VPN/代理，再测试最多 30 个云端初筛节点。通过大陆三轮实测的节点会单独生成 `clash-mainland.yaml` 和 `fast-mainland.yaml`，并复制到桌面 `Direct-NodeHub-Mainland` 文件夹；这两份才是大陆实测订阅。若为 0 个，代表没有节点通过，不会拿云端结果冒充大陆可用。不要上传或提交任何家宽账号密码。

## 发布手机状态页（一次性设置）

仓库已包含 GitHub Pages 自动部署工作流。首次启用时，在 GitHub 仓库页面打开 Settings → Pages，将 Build and deployment 的 Source 设为 GitHub Actions；然后进入 Actions，手动运行 Publish status website。成功后，GitHub 会在部署任务中显示站点地址。此后 public/ 文件更新时会自动重新部署。


## Cloudflare 使用边界

Cloudflare Pages 可以托管静态状态页和订阅文件，但它不会替节点转发代理流量。当前项目不部署 Workers 代理中转：Cloudflare 的 TCP 能力有明确的入站条件和端口/网络限制，且自助服务协议对 VPN 或类似代理服务有禁止条款；为了避免账号和项目被停用，不把它当作免费代理中转方案。
