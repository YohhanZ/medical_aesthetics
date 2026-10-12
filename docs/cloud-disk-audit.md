# 云服务器磁盘占用实测

本页记录部署前只读快照；后续用户授权暂停原项目并完成医美演示部署，最新状态见[部署记录](cloud-demo-deployment.md)。没有清理原镜像、缓存、数据卷或模型目录。

2026-10-13：用户要求查明磁盘占用；仅进行了 SSH 只读元数据检查，没有删除、清理、重启、升级或部署。服务器为 Ubuntu 22.04.5 LTS，Docker 可用；无项目域名。SSH 到期字段修正后连接成功，原 UTC 到期时刻不变。

## 文件系统分配

`df -B1 -T /`：ext4 文件系统总量 42,156,257,280 字节（39.26 GiB），已用 25,580,781,568（23.83 GiB），可用 14,733,615,104（13.72 GiB），64%；inode 使用13%。以下为 `du -x -B1` 实测分配，不与 Docker 逻辑统计重复相加。

| 项目 | 分配大小 | 解释 |
| --- | --- | --- |
| /var/lib/containerd | 11.42 GiB | 镜像内容存储约2.31 GiB、overlayfs快照约9.12 GiB，含运行镜像/构建层 |
| /var/lib/docker | 0.78 GiB | Docker卷约688 MiB、容器目录约111 MiB及元数据 |
| /swapfile | 4.00 GiB | 已启用swap，总使用约913 MiB；不能作为普通缓存删除 |
| /usr | 3.56 GiB | 系统软件与库 |
| /opt/mapmost-rag/models | 2.14 GiB | 原项目模型目录；只统计大小，没有读取模型或业务内容 |
| /var/log | 444 MiB | 其中systemd journal约416 MiB，未清理 |

`du`根目录汇总与`df`已用接近，未显示明显大量未计入目录的已删除占用。本次没有执行lsof检查，因此不宣称证明不存在任何删除未释放文件。

## Docker统计

`docker system df`：8镜像、6使用中，逻辑SIZE 7.096 GB，可回收13.78 MB；6运行容器可写层合计9.449 MB；5卷均使用中、合计583.8 MB；70构建缓存条目，逻辑SIZE 6.035 GB、RECLAIMABLE 3.067 GB（约2.86 GiB）。这些逻辑值含共享层，不能相加当作实际额外空间。实际物理Docker相关目录约12.2 GiB。

主要活动镜像为现有项目后端、Milvus、MySQL及MinIO。缓存可回收是Docker当时估计，不是已清理结果，也不保证某个限时筛选命令必然释放同等大小。数据库/存储卷占用未显示异常大，仍全部作为业务数据保护；不用volume prune或system prune -a --volumes。

## 可审阅清理建议与部署边界

优先候选为未使用的Docker构建缓存，预估约2.9 GiB；清理会降低后续构建缓存命中率，不应清理活动镜像、现有项目models目录、任何业务数据卷或swap。用户这次仅要求查看原因，因此没有执行清理命令。日志总量约444 MiB，不是主要原因；保留期变更待明确需要。

原6个mapmost容器检查后均仍healthy。读取得到可用内存约2.2 GiB，4 GiB swap已使用约913 MiB；释放磁盘不能替代内存扩容。未向用户选择扩容、试运行、复用其原Milvus或公开后台的授权作推断。独立医美部署尚未开始，资源选择仍待确认；域名回答为无。

## 实际检查

- deploy/disk-audit.sh经专用SSH执行，退出0：df/inodes、Docker总量、journal大小、同文件系统根目录分配、容器可写层。
- 后续两轮SSH只读检查均退出0：/var、/opt、Docker/containerd、根目录普通文件大小、Docker共享/独占层和卷汇总、swap、原项目一级目录与日志分配、容器健康状态。
- 目录扫描采用nice19、ionice空闲优先级及超时约束，未读取文件内容、环境变量或凭据。
- 原始元数据保存在被Git忽略的runtime/cloud-preflight-report.txt、cloud-disk-audit.txt、cloud-disk-detail.txt和cloud-disk-project-detail.txt；没有公开业务文件内容。
