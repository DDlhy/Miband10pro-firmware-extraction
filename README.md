# 小米手环 10 Pro（P67）拆解实录：SPI NAND 固件提取与文件系统还原

> 拆机 · 测试点测绘 · 1.8V/3.3V 电平适配 · Radxa Zero 3W SPI 直读 · BCH ECC 纠正 · YAFFS2 / ROMFS 还原
> 设备来源：一台刷写 AP（应用处理器）固件失败而变砖的手环 10 Pro。

| 项 | 内容 |
|---|---|
| 设备 | 小米手环 10 Pro（内部代号 **p67**，主板丝印 LTAM415 / 252216-04） |
| 系统 | 小米 **Vela OS**（NuttX 系 RTOS，BES 平台 SoC） |
| 样本来源 | 刷写 **AP（应用处理器）固件失败变砖**，无法开机，作为拆解研究样本 |
| 目标芯片 | **Dosilicon DS35M4GB-IB** · 4 Gbit SPI NAND · 1.8V · WSON-8（6×8 mm） |
| 读取平台 | Radxa Zero 3W（Rockchip RK3566，40-Pin 的 SPI3_M1） |
| 电平方案 | DCDC 5V→1.8V 供电；SI/SO 各串 2.2 kΩ 做 1.8V⇄3.3V 适配 |
| 镜像 | `DS35M4GB_miband10pro_full_dump_20261010_544MiB.bin`（570,425,344 B） |
| 还原 | BCH ECC 纠错 → YAFFS2 用户数据 → 离线 rootfs **5959 文件**全部校验通过 |

---

## 1. 背景

本次研究对象是一台小米手环 10 Pro（内部代号 **p67**）。该设备此前在一次 **AP（应用处理器）固件刷写**中失败，之后无法开机，判定为变砖设备，因此作为拆解与固件研究样本。

工作目标：

1. 取下主板上的 SPI NAND，完整读出整片 **raw 镜像**（主区 + spare/OOB 区）；
2. 解析 NAND 分区布局与固件格式（AP / BL2 / Factory / OTA / Recovery）；
3. 利用 spare 区的 **BCH ECC** 纠正 raw 读取的位错误，还原 **YAFFS2** 用户数据分区，重建可离线浏览的完整文件系统。

涉及的主要技术点：

- 芯片工作于 **1.8V** 逻辑域，Radxa GPIO 为 **3.3V** 域，需要电平适配；
- WSON-8 无引脚封装，焊盘间距小；
- NAND raw 镜像含 spare 区与 ECC 布局，还原文件系统前需先完成 ECC 纠正与页解析。

## 2. 拆机与取芯

手环外壳与背板（`images/band_shell.jpg`）：

![手环外壳/背板](images/band_shell.jpg)

拆开外壳后，内部主板与排线（`images/mainboard_internal.jpg`）：

![内部主板与排线](images/mainboard_internal.jpg)

拆解过程：拆开手环外壳，取下主板，从主板上取下 WSON-8 封装的 SPI NAND Flash，并将杜邦线焊接至 Flash 引脚引出。

## 3. 目标芯片：DS35M4GB-IB

芯片为东芯半导体（Dosilicon）4 Gbit SPI NAND，数据手册 `datasheet/DS35X4GBXXX_rev07.pdf`（Rev.07，2025-03-14）。

**型号拆解**（DS35X4GB 命名规则）：

| 字段 | 值 | 含义 |
|---|---|---|
| 系列 | 35 | SPI NAND |
| 组织/电压 | **M** | 1.8V，Quad SPI x1/x2/x4（`Q` 为 3.3V 版） |
| 容量 | 4G | 4 Gbit |
| 温度等级 | I | Industrial，-40℃ ~ 85℃ |
| 封装 | B | WSON 6×8 mm（8 引脚） |

**关键参数**（数据手册 FEATURES / Device Parameters）：

| 参数 | 值 |
|---|---|
| 存储组织 | 512M×8 bit 主区 + 32M×8 bit spare（合计 **544 MiB**） |
| 页 / 块 | (2048+128) B/页，64 页/块，(128K+8K) B/块 |
| 块数 | 4096 |
| VCC | 1.7 ~ 1.95 V（M 版） |
| SPI 模式 | Mode 0 / Mode 3 |
| 接口 | 标准 / Dual / Quad SPI（x1/x2/x4） |
| 串行时钟 | 83 MHz（1.8V）/ 104 MHz（3.3V） |
| 页随机读取 | 25 µs（无 ECC）/ 130 µs（有 ECC） |
| 页编程 / 块擦除 | 300 µs / 2 ms（Typ） |
| ECC | 片上 8-bit ECC，默认开启，可用命令启停 |
| 寿命 | 80K P/E cycles；10 年数据保持（8bit/512B ECC） |

WSON-8 顶视图引脚定义（`images/wson8_pinout.jpg`）：

![WSON-8 引脚定义](images/wson8_pinout.jpg)

| Pin | 名称 | 方向 | 说明 |
|---|---|---|---|
| 1 | CS# | I | 片选（低有效） |
| 2 | SO / SIO1 | O | 串行数据输出（MISO） |
| 3 | WP# / SIO2 | I | 写保护（低有效） |
| 4 | VSS | - | 地 |
| 5 | SI / SIO0 | I | 串行数据输入（MOSI） |
| 6 | SCLK | I | 时钟 |
| 7 | HOLD# / SIO3 | I | 暂停（低有效） |
| 8 | VCC | - | 1.8V 电源 |

**常用命令**（Table 1.3 Command Set）：`9Fh` READ ID · `13h` PAGE READ（3B 行地址）· `03h/0Bh` READ FROM CACHE（2B 列地址 + 1 dummy → 2176 B）· `0Fh` GET FEATURE · `1Fh` SET FEATURE · `FFh` RESET · `10h` PROGRAM EXECUTE · `D8h` BLOCK ERASE。

## 4. 主板测试点测绘

在主板背面用万用表量出与 Flash 各引脚对应的测试点（VCC 1.8V、GND 及 CS# / SI / SO / SCLK / WP# / HOLD#），并按主板俯视图绘制成测试点网络图。

测绘结果（`images/mainboard_testpoint_map.jpg`）：

![主板测试点测绘图](images/mainboard_testpoint_map.jpg)

主板背面测试点实测（`images/mainboard_back_testpoints.jpg`）：

![主板背面测试点实测](images/mainboard_back_testpoints.jpg)

| 网络 | 测试点标注 | 电位 |
|---|---|---|
| VCC | 红色标注点 | 1.8V |
| GND | 多处白色标注点 | - |
| CS# / SI / SO / SCLK / WP# / HOLD# | 见测绘图 | - |

## 5. 硬件接线

### 5.1 供电

Radxa 40-Pin 提供 5V（Pin2/Pin4），芯片 VCC 需要 **1.8V**。使用 DCDC 降压模块将 5V 降至 1.8V，为芯片供电：

```
Radxa Zero 3W 40-Pin            DCDC Buck 模块               DS35M4GB
┌──────────────┐  5V      ┌──────────────────┐  1.8V   ┌──────────────┐
│  Pin2 / Pin4 ├─────────▶│  IN   ▏   OUT    ├────────▶│ VCC   (Pin8) │
│   (5V)       │          │  输出调至 1.8V    │         └──────────────┘
└──────────────┘          └─────────┬────────┘
    GND (Pin6) ─────────────────────┴──────────────────▶ VSS (Pin4)
```

供电接线场景（`images/dcdc_power_setup.jpg`）：

![供电接线场景](images/dcdc_power_setup.jpg)

### 5.2 电平转换（1.8V ⇄ 3.3V）

Flash 为 1.8V 逻辑域，Radxa GPIO 为 3.3V 域。SI（MOSI，3.3V → 1.8V）与 SO（MISO，1.8V → 3.3V）两条信号线各串一颗 **2.2 kΩ** 电阻完成电平适配：

- SI 方向：3.3V 输出经 2.2 kΩ 串阻进入 1.8V 输入，串阻限制电流，配合输入端 ESD 保护二极管钳位，将引脚电压约束在安全范围；
- SO 方向：1.8V 输出经 2.2 kΩ 串阻进入 3.3V GPIO 输入，限制电流并抑制飞线振铃/反射。

该方案适用于低速场景；如需更高速度，应改用双向电平转换芯片（如 TXS0108E / SN74LVC2T45）。

### 5.3 接线对照表（Radxa Zero 3W 40-Pin）

引脚号依据 Radxa 官方硬件接口说明（RK3566，SPI3 M1 复用）：

| 信号 | Flash Pin | Radxa 引脚 | 中间元件 | 方向/备注 |
|---|---|---|---|---|
| CS# | 1 | Pin24（SPI3_CS0_M1 / GPIO4_C6） | - | SoC → Flash，片选 |
| SO（MISO） | 2 | Pin21（SPI3_MISO_M1 / GPIO4_C5） | 2.2 kΩ | Flash → SoC |
| WP# | 3 | 建议接 1.8V | - | 保持高电平，禁用写保护 |
| VSS | 4 | GND（Pin6） | - | 共地 |
| SI（MOSI） | 5 | Pin19（SPI3_MOSI_M1 / GPIO4_C3） | 2.2 kΩ | SoC → Flash |
| SCLK | 6 | Pin23（SPI3_CLK_M1 / GPIO4_C2） | - | 时钟 |
| HOLD# | 7 | 建议接 1.8V | - | 读取时需保持高电平，否则芯片挂起 |
| VCC | 8 | DCDC 输出 1.8V | - | 供电 |

焊接细节（`images/wiring_soldering.jpg`、`images/wiring_dupont.jpg`）：

![飞线焊接整体](images/wiring_soldering.jpg)

![杜邦线焊接特写](images/wiring_dupont.jpg)

## 6. Radxa Zero 3W 软件侧配置

启用 SPI 并确认设备节点后，即可在用户态通过 spidev 访问 SPI。启用方式：

```bash
sudo rsetup
# Overlays → Manage overlays → 启用 SPI/spidev 相关 overlay
# （Zero 3W 的 overlay 位于 /boot/dtbo/）
```

重启后确认设备节点：

```bash
ls -l /dev/spidev*
```

设备节点一般为 `/dev/spidev0.0` 或 `/dev/spidev3.0`，以实际枚举为准。

## 7. 固件读取与校验

通过 Radxa Zero 3W 的 GPIO SPI 读取整片镜像，得到 `DS35M4GB_miband10pro_full_dump_20261010_544MiB.bin`。

- 镜像大小：**570,425,344 B（544 MiB）** = 4096 块 × 64 页 × 2176 B，与数据手册容量一致（含每页 128 B spare）；
- 原始 NAND 源哈希（记录于还原产物 `verification.json`）：

```
bc0c07a021200962c357dc58d3da0230b8259233eb4dfdfa7eebd7be92585670
```

命令级读取流程（`9Fh` READ ID / `13h` PAGE READ / `03h` READ FROM CACHE，逐页拼合）参考 `scripts/read_spi_nand.py`。

## 8. 镜像分析

### 8.1 分区与设备节点

根据还原的固件设备文档（`devices.json` / `dev.md`），分区/设备节点布局如下：

| 设备节点 | 挂载点 | 文件系统 | 状态 |
|---|---|---|---|
| `/dev/ap` | -（分区） | - | AP 系统分区，OTA 以 32 KiB 块写入 `vela_ap.bin` |
| `/dev/bl2` | -（分区） | - | 第二阶段启动/升级分区，写入 `vela_bl2.bin` |
| `/dev/resource` | `/resource` | ROMFS | 只读资源分区，正常系统与 Recovery 均挂载 |
| `/dev/nand_data` | `/data` | **YAFFS2** | 主数据 NAND 分区（本次还原主体） |
| `/dev/nand_nv` | `/wasted_nv` | YAFFS2 | BL2 挂载的 NAND 持久区；本机该区域为全 `0xFF`（已擦除） |
| `/dev/nv` | `/misc` | littlefs | **NOR** 分区，未取得（逻辑偏移 `0xFE0000`，长 `0x20000`） |
| `/dev/mode` | `/mode` | littlefs | **NOR** 分区，未取得（逻辑偏移 `0xFC0000`，长 `0x20000`） |
| `/dev/bes_flash` / `/dev/bes_nand` | - | - | BES 平台底层 Flash/NAND 驱动接口 |

### 8.2 固件镜像清单

从 YAFFS 数据与 ECC 纠正结果中恢复的四套固件镜像，及各自内嵌 `/etc` ROMFS 的偏移：

| 镜像 | 来源 | 构建版本 | 内嵌 /etc ROMFS 偏移 / 大小 |
|---|---|---|---|
| `vela_ap.bin`（AP） | `p67-full-ap/watchface-backup-ap.bin` | 3.101.036（`CONBINE_LTALM078_T3.101.036`） | 12,433,648 B / 23,440 B |
| `vela_ota.bin`（OTA 包） | `/data/vela_ota.bin` | 3.101.043 | 452,800 B / 5,136 B |
| `vela_factory.bin`（Factory） | `romfs_ecc_corrected/prebuild/` | 3.101.043 | 2,318,212 B / 3,072 B |
| `vela_recovery.bin`（Recovery） | `romfs_ecc_corrected/prebuild/` | - | 847,108 B / 2,864 B |

AP 固件存在两份字节级略有差异的副本（`watchface-backup-ap.bin` 与 `full-ap-recovery/vela_ap.bin`），两者内嵌 `/etc` ROMFS 字节完全相同；Factory/OTA 的 `build.prop` 与参考文档样本版本不同，还原时保留实际镜像内容。

## 9. 文件系统还原

### 9.1 ECC 纠正

raw 镜像 spare 区带有页级 BCH ECC。还原流程按页提取 spare 中的 ECC 数据，使用软件 BCH 解码（`bchlib`）纠正主区位错误，得到 ECC-corrected 镜像（`romfs_ecc_corrected/`）。

### 9.2 YAFFS2 用户数据还原（`/data`）

对 `/dev/nand_data` 分区做 YAFFS2 解析，还原 Vela OS 用户数据目录：

```text
app/           预装应用：com.shell.liangyi（桌面）、health、home、notifications、
               nfc、perpetual_calendar、quickapp、sport、system、training、
               watchface/builtin（含 AOD）、weather …
apps.json     应用清单
fitness/       健康数据：daily/p0·p32、sport、view、research …
gps/           GPS 记录
misc/         系统杂项
persist.db    持久化数据库（24 KB）
power_event/  开关机/充电事件
usage_stats/  使用统计
vela_ota.bin   OTA 升级包（内含 OTA 阶段固件）
p67-full-ap/  watchface-backup-ap.bin（AP 固件备份，内含 AP /etc ROMFS）
```

### 9.3 完整离线文件系统（rootfs）

以各阶段固件与用户数据重建 p67 AP 命名空间的离线视图：

```text
rootfs/
  etc/        AP 固件内嵌 ROMFS 的 6 个原始配置与脚本
  resource/   主 ROMFS 的 5814 个文件
  data/       YAFFS 最新状态的 139 个文件
  misc/       /dev/nv 挂载点（NOR 分区尚缺）
  mode/       /dev/mode 挂载点（NOR 分区尚缺）
  ota/        /data/ota.zip 挂载点（快照中无 ota.zip）
  watchface/ font/ i18n/   Recovery 阶段 ROMFS loop 挂载点（依赖 /resource/*.bin）
  wasted_nv/  BL2 备用挂载点（NAND 对应区域全 0xFF）
  dev/ proc/ tmp/   运行时命名空间，保留空目录
```

缺失项（`missing_sources.json`）：NOR `nv`/`mode` 分区（`/misc/factory.prop`、`/mode/*`）、BL2 完整镜像、`/data/ota.zip`、`/resource/watchface.bin|font.bin|i18n.bin`（Recovery loop 挂载的 backing 文件）。运行时由 NuttX 驱动注册的设备节点（`/dev/*`）不实例化为普通文件。

## 10. 验证结果

`filesystem_completed_verified/verification.json`：

| 项 | 结果 |
|---|---|
| rootfs 文件 / 子目录 / 字节数 | **5959 / 337 / 219,512,486 B** |
| resource（ROMFS）/ data（YAFFS） | 5814 文件 / 139 文件 |
| 阶段还原 | AP 6 · OTA 6 · Factory 4 · Recovery 3 · BL2 3（共享文件，哈希与文档一致） |
| 文档比对 | 17 份精确匹配 · 3 份源缺失 · 3 份共享文件哈希一致 · 2 份镜像版本不同保留原样 |
| 校验 | 所有输出哈希已验证 · 固件 ROMFS 元数据校验和有效 · 输入源哈希保持 |
| 参考文档 | 32 份 |
| 缺失源 | 10 项 |

全部 5959 个 rootfs 文件与源字节一致，原始 ECC / YAFFS / ROMFS 输入文件保持不变。

成果归档：

| 归档 | 内容 |
|---|---|
| `DS35M4GB_miband10pro_full_dump_20261010_544MiB.zip` | 全片 raw 镜像（单 `.bin`，570,425,344 B） |
| `yaffs_data_restored.zip` | `/data` YAFFS2 用户数据还原 |
| `filesystem_completed_verified.zip` | 完整离线 rootfs + `file_manifest` / `SHA256SUMS` / `mounts.json` / `verification.json` / `tools/` |

数据归档体积较大（raw 镜像约 544 MiB），未随本仓库 zip 附带，建议经 Git LFS 或 Release 页托管。

## 11. 复现

```bash
# 依赖：bchlib、numpy、pyelftools（Python 3）
python3 complete_filesystem.py <ecc_yaffs目录> <system文档目录> --out <新输出目录>
```

脚本与解析器位于 `filesystem_completed_verified/tools/`（`complete_filesystem.py`、`inventory_contents.py`）。组装过程只读取和复制文件，不修改源镜像。

## 12. 参考资料

- 数据手册：`datasheet/DS35X4GBXXX_rev07.pdf`（Dosilicon，Rev.07，2025-03-14）
- Radxa Zero 3W 硬件接口说明（40-Pin 定义）：<https://docs.radxa.com/zero/zero3/hardware-design/hardware-interface>
- Radxa rsetup（Overlay 管理）：<https://docs.radxa.com/en/template/sbc/os-config/rsetup>
- Radxa Zero 3W mraa / SPI：<https://docs.radxa.com/en/zero/zero3/app-development/mraa>
- flashrom：<https://flashrom.org>

---

**LICENSE**：MIT（见 `LICENSE`）。固件内容归原厂商所有，仅作研究用途。
