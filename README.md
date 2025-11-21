# safeinterp

Safe & intelligent 1D interpolation and extrapolation engine for Python.

> Adaptive curve selection, multi-segment fitting, and robust extrapolation – all with a simple, NumPy-friendly API.

---

## Features

- ✅ **Safe preprocessing**
  - 自动排序 x，去重、去除过近点，避免除零与奇异行为
  - 检查 NaN / Inf，给出清晰报错信息

- ✅ **智能插值（auto 模式）**
  - 在 `linear / power / exp / logistic / cos / sin / poly2 / poly3` 中自动择优
  - 对每一小段自动选择 `(mode, k)`，尽量平滑、贴合整体趋势
  - 内置单调性约束，尽量避免局部“反冲”“抖动”

- ✅ **多种曲线形状（手动模式）**
  - `linear` 线性
  - `power` 幂函数
  - `exp` 指数
  - `logistic` S 型
  - `sin` / `cos` 缓入缓出
  - `poly2` / `poly3` 平滑多项式

- ✅ **安全外推（extrapolation）**
  - `edge / linear / exp / power / mirror / auto`
  - `auto` 模式会自动在多种策略之间 fallback，失败时退化到最安全的 `edge`

- ✅ **批量插值 `batch_interp_curve`**
  - 多类别（多区域、多技术、多情景）统一或独立插值
  - 支持：
    - 每个类别自己的 `x/y/new_x`
    - 或继承公共 `common_x / common_new_x`
    - 或使用 `start/end/num` 定义单段演化

- ✅ **零依赖（仅依赖 NumPy）**
  - 适合数值模型、能源系统规划、经济模型、情景模拟等场景

---

## Installation

> PyPI 版本即将发布，当前可以通过源码方式安装。

```bash
git clone https://github.com/mrbinxu2025-dotcom/safeinterp.git
cd safeinterp
pip install -e .
