# safeinterp

Safe & intelligent 1D interpolation and extrapolation engine for Python.

> Adaptive curve selection, multi-segment fitting, and robust extrapolation – all with a clean, NumPy-friendly API.

<p align="center">
  <a href="https://github.com/mrbinxu2025-dotcom/safeinterp/stargazers">
    <img src="https://img.shields.io/github/stars/mrbinxu2025-dotcom/safeinterp?style=social" />
  </a>
  <a href="https://github.com/mrbinxu2025-dotcom/safeinterp/actions">
    <img src="https://img.shields.io/github/actions/workflow/status/mrbinxu2025-dotcom/safeinterp/python-package.yml?label=build" />
  </a>
  <a href="https://pypi.org/project/safeinterp/">
    <img src="https://img.shields.io/pypi/v/safeinterp?color=blue" />
  </a>
  <a href="https://github.com/mrbinxu2025-dotcom/safeinterp/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/mrbinxu2025-dotcom/safeinterp" />
  </a>
</p>

---

## 🚀 Features / 特性概览

- ✅ **Safe preprocessing / 安全预处理**
  - 自动排序 `x`，去除重复点与“两点过近”的奇异情况
  - 自动检查 `NaN / Inf` 并提供清晰的错误信息

- ✅ **Intelligent auto-mode / 智能插值 (`mode="auto"`)**
  - 自动从 `linear / power / exp / logistic / cos / sin / poly2 / poly3` 中择优
  - 对每一小段自动搜索最合适的 `(mode, k)`
  - 内置整体趋势与单调性约束，减少反冲 / 锯齿抖动

- ✅ **Rich curve families / 多种曲线形状（手动模式）**
  - `linear`：线性  
  - `power`：幂函数  
  - `exp`：指数  
  - `logistic`：S 型  
  - `sin` / `cos`：缓入缓出  
  - `poly2` / `poly3`：平滑多项式（smoothstep 风格）

- ✅ **Safe extrapolation / 安全外推**
  - 支持 `edge / linear / exp / power / mirror / auto`
  - `auto` 模式会自动尝试多种策略，异常时自动 fallback
  - 尽量避免“爆炸式外推”，优先使用更稳健的边界行为

- ✅ **Batch interpolation / 批量插值**
  - `batch_interp_curve` 支持多区域、多技术、多情景批量插值
  - 每个类别可以：
    - 使用自己的 `x / y / new_x`
    - 或继承公共 `common_x / common_new_x`
    - 或用 `start / end / num` 定义单段演化曲线
  - 完全复用 `interp_curve` 的全部能力

- ✅ **NumPy-only / 零额外依赖**
  - 仅依赖 NumPy
  - 适合数值模型、能源系统规划、经济模型与情景模拟等场景

---

## ❓ Why safeinterp? / 为什么要用 safeinterp？

大多数插值库在以下情况会失败或产生危险结果：

| 常见问题                     | 常见库表现           | safeinterp 行为                  |
|------------------------------|----------------------|----------------------------------|
| `x` 乱序 / 重复点            | ❌ 报错或结果不稳定  | ✔ 自动排序与去重                |
| 间距极小 / 极短区间          | ❌ 斜率爆炸 / 抖动   | ✔ 自动修正，避免除零与奇异行为  |
| `y` 非单调，趋势复杂         | ❌ 曲线突然反转      | ✔ 内置趋势检测与趋势约束        |
| 指数 / 幂律外推              | ❌ 极易爆炸或崩溃    | ✔ 多策略外推 + 自动 fallback     |
| 多段曲线、不同段需要不同形状 | ❌ API 不支持        | ✔ 每段可自动/手动选择 `(mode, k)` |

safeinterp 的目标是：

> 尽量做到：不崩溃、不乱炸、少反冲，在复杂情景下仍然给出“看得懂、信得过”的曲线。

---

## 🔧 Installation / 安装

> 🔜 计划发布到 PyPI。发布后你可以直接：

```bash
pip install safeinterp
````

在发布到 PyPI 之前，可以通过源码方式安装：

```bash
git clone https://github.com/mrbinxu2025-dotcom/safeinterp.git
cd safeinterp
pip install -e .
```

---

## 🚀 Quickstart / 快速上手

### 1. 简单插值

```python
from safeinterp import interp_curve

x = [0, 10, 20, 30]
y = [0, 2, 8, 9]

values = interp_curve(x=x, y=y, new_x=[5, 15, 25])
print(values)
```

---

### 2. Auto 模式（智能插值）

```python
from safeinterp import interp_curve

x = [0, 10, 20, 30]
y = [0, 2, 8, 9]
new_x = range(0, 31)

values = interp_curve(x=x, y=y, new_x=new_x, mode="auto")
```

---

### 3. 多段手动模式（自定义每一段的形状）

```python
from safeinterp import interp_curve

x = [0, 10, 20, 30]
y = [0, 2, 8, 9]
new_x = range(0, 31)

segments = [
    {"mode": "linear"},             # [0,10]
    {"mode": "power", "k": 1.5},    # [10,20]
    {"mode": "cos"},                # [20,30]
]

values = interp_curve(x=x, y=y, new_x=new_x, segments=segments)
```

---

### 4. 批量插值（多区域 / 多技术）

```python
from safeinterp import batch_interp_curve

data = {
    "solar": {
        "y": [0, 5, 15],
        "mode": "auto",
    },
    "wind": {
        "y": [0, 3, 12],
        "mode": "power",
        "k": 1.2,
    },
}

results = batch_interp_curve(
    data,
    common_x=[2020, 2030, 2040],
    common_new_x=range(2020, 2041),
)

solar_curve = results["solar"]
wind_curve = results["wind"]
```

---

## 📊 Examples / 示例图

> 建议在仓库中放置 `assets/basic.png`, `assets/modes.png`, `assets/extrap.png`，并在下方插入示例图。

### Basic Interpolation

![basic](assets/basic.png)

### Curve Modes

![modes](assets/modes.png)

### Extrapolation Example

![extrap](assets/extrap.png)

---

## 🗺 Roadmap / 路线图

* [ ] 2D surface interpolation（二位曲面插值）
* [ ] Monotonic Hermite mode（单调 Hermite 模式）
* [ ] Smoothing spline mode（平滑样条模式）
* [ ] Visualization helper API（可视化辅助接口）
* [ ] 发布 PyPI 正式版本
* [ ] 在线 Demo（Colab / Binder）

---

## 🤝 Contributing / 参与贡献

欢迎：

* PR（Pull Request）
* Issue（问题反馈 / Bug 报告）
* Feature Request（新特性建议）

如果你在能源系统、经济模型或其他数值仿真中使用了 **safeinterp**，
也非常欢迎在 Issue 里分享你的使用场景。

> 如果你觉得 **safeinterp** 对你有帮助，请点一个 ⭐ Star 支持一下。

---

## 📄 License / 许可证

本项目基于 MIT License 开源。

```text
MIT License

Copyright (c) 2025

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the “Software”), to deal
in the Software without restriction, including without limitation the rights  
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell  
copies of the Software, and to permit persons to whom the Software is  
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in  
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR  
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,  
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE  
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER  
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,  
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN  
THE SOFTWARE.
```
