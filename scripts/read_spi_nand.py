#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DS35M4GB (4Gbit SPI NAND, 1.8V) 全片读取参考脚本
=================================================
目标平台：Radxa Zero 3W（RK3566），经 /dev/spidev* 访问 SPI。

命令参考：DS35X4GBXXX_rev07.pdf Table 1.3 Command Set
  READ ID          0x9F            -> 2 bytes（厂商/器件 ID）
  GET FEATURE      0x0F + 1 addr   -> 1 byte（可查 ECC/状态位）
  PAGE READ        0x13 + 3B row   -> 页面载入缓存（块 RA[17:6] | 页 RA[5:0]）
  READ FROM CACHE  0x03 + 2B col + 1 dummy -> 2176 B（2048 主区 + 128 spare）
  RESET            0xFF

说明：
  - 帧格式细节（dummy 布局、tR 等待时长）以数据手册 §3.3 Read Operations 为准；
  - 本脚本为工程参考实现，实际现场读取流程可按你的方案等价替换
    （亦可用 flashrom -p linux_spi:dev=/dev/spidevX.Y,spispeed=4000）。
  - 全片读取：262144 页 × 2180 B ≈ 544 MiB，4 MHz 下约 20 分钟；可提高
    max_speed_hz 或改用 0x0B/多页 cache 预取加速。

用法：
  python3 read_spi_nand.py /dev/spidev0.0 dump.bin [spispeed_hz]
"""

import sys
import time
import spidev

PAGE_SIZE = 2176          # (2048 + 128) B
PAGES_PER_BLOCK = 64
BLOCK_COUNT = 4096
PAGE_COUNT = BLOCK_COUNT * PAGES_PER_BLOCK   # 262144

CMD_PAGE_READ = 0x13      # 页面载入缓存
CMD_READ_CACHE = 0x03     # 从缓存输出数据（0x0B 同为 read-from-cache）
CMD_READ_ID = 0x9F
CMD_RESET = 0xFF


def open_spi(dev_path: str, speed_hz: int = 4_000_000, mode: int = 0):
    """从 /dev/spidevX.Y 解析 bus/device 并打开"""
    name = dev_path.rsplit("/", 1)[-1]          # spidevX.Y
    bus, dev = name[len("spidev"):].split(".")
    spi = spidev.SpiDev()
    spi.open(int(bus), int(dev))
    spi.max_speed_hz = speed_hz
    spi.mode = mode                             # DS35X4GB 支持 Mode 0 / Mode 3
    return spi


def read_id(spi) -> bytes:
    """
    9Fh：读取厂商/器件 ID。
    帧格式（数据手册 Figure 3.9）：9Fh + 1 dummy byte + 2 bytes ID
    DS35M4GB（1.8V, 4Gbit）→ E5h（厂商） 64h（器件，Table 3.2）
    """
    out = spi.xfer2([CMD_READ_ID, 0x00, 0x00, 0x00])   # 命令 + dummy + 2B 读
    return bytes(out[2:])


def read_page(spi, page_idx: int, t_r: float = 0.0002) -> bytes:
    """
    读取一页（主区 + spare）。
    1) 13h + 3B 行地址，把目标页载入缓存；
    2) 等待 tR（数据手册：130 µs @ ECC / 25 µs 无 ECC，留裕量）；
    3) 03h + 2B 列地址(=0) + 1 dummy，读出 PAGE_SIZE 字节。
    """
    block = page_idx // PAGES_PER_BLOCK
    page = page_idx % PAGES_PER_BLOCK
    row = (block << 6) | page                   # RA[17:0]

    spi.xfer2([CMD_PAGE_READ,
               (row >> 16) & 0xFF, (row >> 8) & 0xFF, row & 0xFF])
    time.sleep(t_r)

    out = spi.xfer2([CMD_READ_CACHE, 0x00, 0x00, 0x00] + [0] * PAGE_SIZE)
    return bytes(out[4:])


def dump(spi, path: str):
    """顺序读取全片（4096 块 × 64 页）"""
    total = PAGE_COUNT * PAGE_SIZE              # 570,425,344 B = 544 MiB
    print(f"[*] 开始读取 {total} bytes（{PAGE_COUNT} 页 × {PAGE_SIZE}B）...")
    t0 = time.time()
    with open(path, "wb") as f:
        for i in range(PAGE_COUNT):
            f.write(read_page(spi, i))
            if i % 16384 == 0:
                done = (i + 1) / PAGE_COUNT * 100
                print(f"    {done:5.1f}%  page {i}", flush=True)
    print(f"[*] 完成，用时 {time.time() - t0:.1f}s -> {path}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)
    dev = sys.argv[1]
    out = sys.argv[2]
    speed = int(sys.argv[3]) if len(sys.argv) > 3 else 4_000_000

    spi = open_spi(dev, speed)
    try:
        spi.xfer2([CMD_RESET])
        time.sleep(0.001)
        rid = read_id(spi)
        print(f"[*] READ ID: {rid.hex()}（期望 e564 = DS35M4GB, 1.8V/4Gbit）")
        if rid != bytes([0xE5, 0x64]):
            print("[!] 器件 ID 与 DS35M4GB 不符，请核对接线/CS 与时钟，或降低速率。")
            sys.exit(2)
        dump(spi, out)
    finally:
        spi.close()


if __name__ == "__main__":
    main()
