# 云端演示部署初检

最新：已按用户后续授权暂停原项目并完成本项目HTTPS8080云演示部署/验收，见[最终部署记录](cloud-demo-deployment.md)。以下是最初预检与SSH排查历史，不能当作当前未部署状态。

2026-10-13 用户确认用于演示/面试展示，提供腾讯云4核/4 GB内存/3 Mbps、公网IP 43.142.39.108。用户随后提供SSH用户名ubuntu、通过腾讯云控制台登录，并说明服务器已有一个项目；SSH修正后已只读登录，Ubuntu 22.04.5 LTS、Docker已安装、根盘可用13.72 GiB、内存可用约2.2 GiB、4 GiB swap已用约913 MiB；现有6个mapmost容器均healthy，端口8080占用，用户确认无域名。没有安装、部署、清理、修改防火墙或更改现有项目配置。下文认证准备为历史记录，最新磁盘检查见cloud-disk-audit.md。

## 已检查

- 对用户指定IP仅检查TCP22，结果可连接；不能据此推断认证可用、OS或服务资源。
- 本机 `ssh -G` 解析的用户为当前Windows用户名86152，端口22及默认identityfile路径；没有将该用户名作为服务器账号尝试登录，没有读取私钥或打印凭据。
- 当前工程包括PostgreSQL、Neo4j、Milvus/etcd/MinIO、可信API和每轮512 MiB沙箱，尚无完整云部署Compose/前后端API镜像/备份恢复与CI/CD交付。

## 资源判断

[Milvus v2.5 Docker Compose官方要求](https://milvus.io/docs/v2.5.x/prerequisite-docker.md)列出Standalone内存8 GB、推荐16 GB（取决于数据量），CPU建议4核或更多。用户4 GB低于该内存要求，而且还需同时运行其他服务，不能把小数据、空闲时占用或调低配额当作整套稳定性的证明。当前不更换Milvus、不关闭沙箱、不将缺失的检索伪装为已部署，不直接启动无预算的整套服务。

登录后先只读检查CPU/指令集、总/空闲内存、swap、磁盘、OS、Docker及现有服务/端口，再决定部署边界。若保持4 GB，需实测低并发小集是否可演示或把存储组件拆到独立节点；完整单机的内存升级/新增托管资源须用户选择，不能擅自购买或更改云规格。3 Mbps下静态资源体积、缓存及镜像/数据传输时间也需核实。

## 下一步

已尝试ubuntu账号与本机既有SSH身份，StrictHostKeyChecking=yes，主机校验通过但认证Permission denied(publickey,password)；没有登录成功，不能推断具体密钥或密码配置。需用户在ubuntu控制台追加已准备的项目专用公钥；不让用户粘贴私钥或密码。拿到认证条件后，检查系统/Docker/现有业务，完成可审阅部署配置和资源验证，再按演示环境范围部署。模拟标识、独立审核、认证/门店授权、本人确认、幂等及模型出口限制保留；不把云端演示视为真实医疗生产上线。


## 项目专用SSH认证准备（2026-10-13）

已准备runtime/cloud-demo-id-ed25519和.pub、runtime/cloud-demo-add-key.sh，全部git check-ignore通过；私钥权限为当前用户可读、SYSTEM/本机管理员权限，无继承普通用户权限。初次本地ssh-keygen返回255但文件已产生，没有把退出码当成功；通过专用文件派生公钥exit0并规范化/校验公钥格式，未输出私钥。没有改动用户原id_rsa、SSH配置或远端授权。

追加脚本限定当前用户为ubuntu，追加到其authorized_keys、不覆盖原列表，使用restrict及三天到期的expiry-time（初版误用新版Z后缀，版本兼容修正见下文）；操作将给本机该新公钥ubuntu访问能力，需用户在控制台执行这个明确授权步骤。SSH banner为OpenSSH8.9p1 Ubuntu-3ubuntu0.15，未据此声称已确认系统版本。三天到期格式与限制依据[OpenSSH手册](https://man.openbsd.org/sshd.8)；[腾讯云控制台密钥绑定](https://cloud.tencent.com/document/product/213/16691)需要关机，本次提供终端追加方法，不走停机绑定流程。

新增[deploy/preflight.sh](../deploy/preflight.sh)，只读采集OS字段、CPU/指令集、free/df、监听端口、进程名称/RSS、Docker版本/容器/资源统计；不读取.env/凭据/业务数据，不安装、重启、改权限或操作数据库。两个脚本在本地无网络、只读、非root容器中分别bash -n通过；只是语法检查，不代表已在云服务器执行。

当前仍未云登录、部署、安装或修改原项目；等待用户完成公钥追加后，先只读检查资源/现有业务/端口，再制定隔离部署方案。仍不关闭Milvus/沙箱或降低授权、知识审核、本人确认和幂等要求来伪装上线。密钥/public-key准备文件不提交；服务器后续行为按用户实际授权与资源判断进行。


## 公钥添加后的连接复核

用户回复已添加，到期时间20261015172852Z。使用专用私钥、IdentitiesOnly=yes、BatchMode=yes、StrictHostKeyChecking=yes重试ubuntu连接，仍返回255/Permission denied；预检没有在服务器执行。客户端认证元数据确认Offering public key ED25519 SHA256:d0tytAMhPlNYLPwCliK6COt1KB6fa1fm5t6f2B6K4Pw，与本机公钥指纹一致，服务器未接受；不能凭此断言远端文件权限、HOME、条目换行、到期或sshd策略的具体问题。

新增deploy/ssh-auth-check.sh供用户在ubuntu控制台只读获取时钟/账号HOME、实际ubuntu主目录及authorized_keys权限、项目公钥条目/指纹与有限sshd拒绝元数据。脚本本地离线只读非root容器bash -n通过，不输出私钥或密码哈希，不修改权限或SSH配置，不重启服务。等待服务器端输出后再作有证据的修复；不反复盲目加钥或全局放宽认证，不改动现有项目。


## OpenSSH 8.9 到期格式修正（待控制台执行）

用户回传HOME=/home/ubuntu、ubuntu属主及主目录750/.ssh700/authorized_keys600，公钥第2行与预期相符，pubkeyauthentication yes、strictmodes yes、authorizedkeysfile为默认路径。未发现这些字段异常；未获取完整sshd拒绝日志。专用密钥重试仍255，尚未登录。

初版追加命令引用新版OpenBSD格式，未按服务器OpenSSH_8.9p1版本核对，这是本次准备错误。[8.9p1官方parse_absolute_time源码](https://github.com/openssh/openssh-portable/blob/V_8_9_P1/misc.c#L2270)只接受8/12/14位时间，按本地时区mktime解析；15位20261015172852Z不合法。[该版本auth-options源码](https://github.com/openssh/openssh-portable/blob/V_8_9_P1/auth-options.c#L373)在expiry-time解析失败时拒绝选项。这个条目存在明确兼容性错误；修正后是否还有其他认证问题须SSH重试确认。

新增deploy/ssh-expiry-repair.sh：仅匹配已确认的完整公钥、restrict、原到期时间和项目注释；从2026-10-15 17:28:52 UTC换算服务器系统本地14位时间，忽略控制台TZ变量，不延长授权时段；完整备份后仅替换该条目到期字段。缺失/重复/不同公钥拒绝写入；已修正可重复执行；不改其他公钥、StrictModes或sshd配置，不重启服务。runtime/cloud-demo-add-key.sh也改为兼容本地14位格式。

本地以无网络、只读根目录、非root临时Docker容器实测：bash语法检查、精确条目修正、其他字节及无末尾换行保持、600权限、原文件备份、幂等、缺失/重复/错误公钥拒绝、环境TZ覆盖忽略均通过。只用合成其他条目，没有读取或修改实际authorized_keys。待用户在ubuntu控制台执行修正后再用严格主机验证重试，成功后才运行只读资源预检。未云部署或修改现有项目。


## 认证与只读预检已通过

用户控制台完成修正，输出20261016012852（服务器本地时间），对应原2026-10-15 17:28:52 UTC。专用SSH与deploy/preflight.sh执行成功exit0。现有项目隔离和资源数据已记录；用户随后要求先查磁盘，三轮只读排查完成，详见[磁盘实测](cloud-disk-audit.md)。没有清理、复用原Milvus、安装或部署；用户尚未选择扩容或4 GB受限试运行，不把磁盘检查当资源方案授权。
