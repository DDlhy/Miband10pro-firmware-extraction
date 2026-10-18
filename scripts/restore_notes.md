# 文件系统还原流程说明

本文档根据实际还原产物（`yaffs_data_restored/`、`filesystem_completed_verified/`）整理，
描述从 raw NAND 镜像到可浏览文件系统的处理链。所有关键步骤均有对应产物与哈希记录。

## 处理链总览

```
DS35M4GB raw dump（570,425,344 B = 544 MiB，含 128 B/页 spare）
        │
        ▼
① 页面解析 + BCH ECC 纠正（使用 spare 区 ECC 字节，软件解码）
        │  → romfs_ecc_corrected/prebuild/{vela_factory.bin, vela_recovery.bin, ...}
        ▼
② YAFFS2 解析（/dev/nand_data 分区）
        │  → yaffs_data_restored/（app、fitness、gps、persist.db、vela_ota.bin、p67-full-ap/...）
        ▼
③ ROMFS 提取（各阶段固件内嵌 /etc，及 /resource 主 ROMFS）
        │  → images/{ap,factory,ota,recovery}_etc.romfs
        ▼
④ 离线 rootfs 组装 + 校验（complete_filesystem.py）
        │  → filesystem_completed_verified/rootfs/（5959 文件）
        ▼
⑤ 验证：file_manifest / SHA256SUMS / verification.json
```

## ① BCH ECC 纠正

- 输入：raw 镜像按页拆分的主区 + spare 区；
- 算法：BCH 解码（Python `bchlib`），ECC 纠错能力 8 bit/512 B（与数据手册
  Parameter Page Byte 112 一致）；
- 输出：ECC-corrected 镜像目录（`romfs_ecc_corrected/`），供后续 YAFFS/ROMFS 解析。

## ② YAFFS2 用户数据还原（/data）

- 定位 `/dev/nand_data` 分区在镜像中的范围（可从 YAFFS2 chunk 头/对象头特征识别）；
- 按 YAFFS2 对象头 + chunk 数据恢复文件、目录与硬链接；
- 关键产物：`apps.json`、`app/com.shell.liangyi/`（桌面应用）、`fitness/`（健康数据）、
  `persist.db`、`vela_ota.bin`（OTA 包）、`p67-full-ap/watchface-backup-ap.bin`（AP 固件备份）。

## ③ ROMFS 提取

各阶段固件内嵌 `/etc` ROMFS 的偏移与大小（已记录在 `stage_inventory.json`）：

| 镜像 | /etc ROMFS 偏移 | 大小 | 版本 |
|---|---|---|---|
| vela_ap.bin | 12,433,648 | 23,440 | 3.101.036 |
| vela_ota.bin | 452,800 | 5,136 | 3.101.043 |
| vela_factory.bin | 2,318,212 | 3,072 | 3.101.043 |
| vela_recovery.bin | 847,108 | 2,864 | - |

提取命令等价于：定位偏移 → 校验 ROMFS magic/卷校验和 → 按 ROMFS inode 表导出文件。

## ④ 离线 rootfs 组装

```bash
python3 complete_filesystem.py <ecc_yaffs目录> <system文档目录> --out <新输出目录>
```

- 依赖：`bchlib`、`numpy`、`pyelftools`；
- 组装过程只读取和复制文件，不修改源镜像；
- 对文档中列出但当前快照不存在的路径（如 `/data/log`、录音、支付）不做空文件占位，
  以 `missing_sources.json` 记录缺口。

## ⑤ 验证

- `file_manifest.json` / `.tsv`：每个还原文件的哈希与来源；
- `SHA256SUMS.txt`：全量校验和；
- `verification.json`：rootfs 5959 文件 / 219,512,486 B 与源字节一致；
  固件 ROMFS 元数据校验和有效；输入源哈希保持；
- `mounts.json`：各挂载点与恢复状态（recovered / source_partition_missing /
  erased_partition / runtime_generated / archive_not_in_snapshot）。

## 未还原项

- **NOR 分区**：`/dev/nv`（`/misc`，偏移 `0xFE0000`，长 `0x20000`）、`/dev/mode`
  （偏移 `0xFC0000`，长 `0x20000`），需对应 NOR 芯片的读取；
- BL2 完整镜像（仅 3 个共享文件与文档哈希一致）；
- `/data/ota.zip`、`/resource/{watchface,font,i18n}.bin`（Recovery loop 挂载的 backing 文件）。
