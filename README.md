# safeinterp

Safe & intelligent 1D interpolation and extrapolation engine for Python.

> Adaptive curve selection, multi-segment fitting, and robust extrapolation – all with a simple, NumPy-friendly API.

<p align="center">
  <a href="https://github.com/mrbinxu2025-dotcom/safeinterp/stargazers">
    <img src="https://img.shields.io/github/stars/mrbinxu2025-dotcom/safeinterp" />
  </a>
  <a href="https://github.com/mrbinxu2025-dotcom/safeinterp/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/mrbinxu2025-dotcom/safeinterp" />
  </a>
</p>

---

## Features / 特性概览

- ✅ **Safe preprocessing / 安全预处理**
  - 自动排序 `x`，去除重复与“过近”点，避免除零与奇异行为
  - 检查 NaN / Inf，给出清晰的报错信息

- ✅ **Intelligent interpolation (`mode="auto"`) / 智能插值**
  - 在 `linear / power / exp / logistic / cos / sin / poly2 / poly3` 中自动择优
  - 对每一小段自动选择 `(mode, k)`，尽量平滑、贴合整体趋势
  - 内置单调性约束，尽量避免“反冲”“锯齿抖动”

- ✅ **Rich curve families / 多种曲线形状（手动模式）**
  - `linear`：线性
  - `power`：幂函数
  - `exp`：指数
  - `logistic`：S 型
  - `sin` / `cos`：缓入缓出
  - `poly2` / `poly3`：平滑多项式（smoothstep 风格）

- ✅ **Safe extrapolation / 安全外推**
  - 支持 `edge / linear / exp / power / mirror / auto`
  - `auto` 模式会在多种策略之间自动 fallback，最后退化到最安全的 `edge`

- ✅ **Batch interpolation / 批量插值接口**
  - `batch_interp_curve` 支持多类别（多区域、多技术、多情景）统一或独立插值
  - 每个类别可以：
    - 使用自己的 `x / y / new_x`
    - 或继承公共 `common_x / common_new_x`
    - 或使用 `start / end / num` 定义单段演化

- ✅ **NumPy-only / 零额外依赖**
  - 仅依赖 NumPy，适合数值模型、能源系统规划、经济模型与情景模拟等场景

---

## Installation / 安装

> 🔜 计划发布到 PyPI。当前可以通过源码方式安装：

```bash
git clone https://github.com/mrbinxu2025-dotcom/safeinterp.git
cd safeinterp
pip install -e .
