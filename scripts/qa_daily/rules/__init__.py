"""九游质检的业务规则（不进 Artemis 内核）。

每个模块只做一件事，run_daily.py 按顺序调用：
- capacity: 空间预算（3× 包体积）、可回收候选、卸载
- cleanup:  设备清场（force-stop 往期游戏）、收尾、内存观测
- recovery: 崩溃识别与重启（CRASH 与 FAIL/TIMEOUT 区分）
"""
