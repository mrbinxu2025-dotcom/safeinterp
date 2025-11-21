import numpy as np
from typing import Tuple, Sequence, Union, Optional, Dict, Any

ArrayLike = Union[Sequence[float], np.ndarray]


# ============================================================
#  工具函数：保证 x 有序且不重复（防止除零 / 奇异行为）
# ============================================================
def _ensure_sorted_xy(x: ArrayLike, y: ArrayLike) -> Tuple[np.ndarray, np.ndarray]:
    """
    对 (x, y) 进行统一预处理：
    1. 转为 float 型 np.ndarray
    2. 检查长度一致、无 NaN/Inf
    3. 按 x 升序排序
    4. 去掉重复或过于接近的 x（避免 span = 0）

    返回
    ----
    x_sorted, y_sorted : 预处理后的数组
    """
    x = np.asarray(x, float)
    y = np.asarray(y, float)

    # 1）长度检查
    if x.shape != y.shape:
        raise ValueError(f"x 与 y 长度不一致：x.shape={x.shape}, y.shape={y.shape}")

    # 2）检查是否存在 NaN / Inf
    if not np.all(np.isfinite(x)) or not np.all(np.isfinite(y)):
        raise ValueError("x 或 y 中存在 NaN 或无穷大，请先清洗数据。")

    # 3）若 x 非单调，先排序
    if np.any(np.diff(x) < 0):
        idx = np.argsort(x)
        x = x[idx]
        y = y[idx]

    # 4）去掉重复或距离过小的 x，防止后续 (x1 - x0) 为 0
    valid_mask = np.concatenate(([True], np.diff(x) > 1e-12))
    if not np.all(valid_mask):
        x = x[valid_mask]
        y = y[valid_mask]

    return x, y


# ============================================================
#  核心类：CurveInterpolator
#  - 负责：插值 / 自动分段 / 自动选择 mode + k / 外推
#  - 对外一般不直接用，通过 interp_curve(...) 调用即可
# ============================================================
class CurveInterpolator:
    """
    自适应一维插值与外推引擎。

    功能特性
    --------
    1. 支持多种单段曲线形状：linear / power / exp / logistic / cos / sin / poly2 / poly3
    2. 高级 auto 模式：
       - 每一段自动从多种模式+参数中选取“最平滑、最符合整体趋势”的组合
       - 通过代价函数综合考虑：斜率贴合、段内平滑、单调性约束等
    3. 自动多段拟合：
       - 若提供多点 (x, y)，auto 模式下自动对每一小段选型
    4. 外推策略：
       - edge / linear / exp / power / mirror / auto
    """

    # --------------------------------------------------------
    #  初始化：预处理数据 + 预估全局斜率 + 判定整体单调性
    # --------------------------------------------------------
    def __init__(self, x: ArrayLike, y: ArrayLike):
        # 排序 + 去重保护 + 基本检查
        x, y = _ensure_sorted_xy(x, y)
        self.x = x
        self.y = y
        self.n = len(x)
        if self.n < 2:
            raise ValueError("至少需要两个有效点")

        # —— 段配置缓存（自动分段 / 手动分段）——
        self._auto_segments_cache = None
        self._seg_modes_cached: Optional[np.ndarray] = None
        self._seg_ks_cached: Optional[np.ndarray] = None
        self._seg_cache_id: Optional[int] = None  # 用于识别不同的 segments 对象

        # —— 估计全局斜率，用于 auto_smooth —— 
        self._slopes = self._estimate_slopes(self.x, self.y)

        # —— 判断整体单调性，用于 auto_monotonic —— 
        dy_all = np.diff(self.y)
        if np.all(dy_all >= -1e-12):
            self._monotonic_dir = 1   # 整体单调递增
        elif np.all(dy_all <= 1e-12):
            self._monotonic_dir = -1  # 整体单调递减
        else:
            self._monotonic_dir = 0   # 非单调

    # --------------------------------------------------------
    #  0. 估计全局斜率数组（每个原始点对应一个“目标斜率”）
    # --------------------------------------------------------
    @staticmethod
    def _estimate_slopes(x: np.ndarray, y: np.ndarray) -> np.ndarray:
        """
        使用差分估计每个原始点处的“目标斜率”，用于 auto 模式中
        让每段插值的起止斜率尽量贴合整体趋势（更平滑、更自然）。
        """
        x = np.asarray(x, float)
        y = np.asarray(y, float)
        n = len(x)
        s = np.zeros_like(y)

        if n == 2:
            dx = x[1] - x[0]
            s[:] = (y[1] - y[0]) / (dx if abs(dx) > 1e-12 else 1.0)
            return s

        dx = np.diff(x)
        dy = np.diff(y)

        # 内点：中心差分
        s[1:-1] = (y[2:] - y[:-2]) / (x[2:] - x[:-2])

        # 两端：向前 / 向后差分
        s[0] = dy[0] / (dx[0] if abs(dx[0]) > 1e-12 else 1.0)
        s[-1] = dy[-1] / (dx[-1] if abs(dx[-1]) > 1e-12 else 1.0)

        return s

    # --------------------------------------------------------
    #  1. 单段比例函数（0~1 → 0~1），控制曲线形状
    # --------------------------------------------------------
    @staticmethod
    def _curve_ratio(t: np.ndarray, mode: str = "linear", k: float = 1.0) -> np.ndarray:
        """
        将归一化自变量 t ∈ [0, 1] 映射到 [0, 1] 的“形状函数”。

        参数
        ----
        t : np.ndarray
            归一化坐标（0~1）
        mode : str
            形状类型：
            - 'linear'   : 线性
            - 'power'    : 幂函数
            - 'exp'      : 指数型
            - 'logistic' : S 型
            - 'cos'      : Cosine 缓入缓出
            - 'sin'      : Sine 缓入缓出
            - 'poly2'    : 二次多项式缓入缓出
            - 'poly3'    : 三次 Smoothstep
        k : float or array-like
            形状控制参数，对 power / exp / logistic 有效。
            可为标量或与 t 同形状数组。
        """
        t = np.asarray(t, float)

        if mode == "linear":
            return t

        elif mode == "power":
            # k 可为标量或数组，交给 numpy 广播
            return t ** k

        elif mode == "exp":
            # 指数型：支持标量 k 或数组 k
            t_arr = t
            k_arr = np.asarray(k, float)
            try:
                k_arr = np.broadcast_to(k_arr, t_arr.shape)
            except ValueError:
                raise ValueError("exp 模式下 k 的形状无法与 t 广播匹配")

            out = np.empty_like(t_arr, float)

            # very small k → 退化为线性
            small = np.abs(k_arr) < 1e-9
            if np.any(small):
                out[small] = t_arr[small]

            # 正常指数情况
            mask = ~small
            if np.any(mask):
                k2 = k_arr[mask]
                t2 = t_arr[mask]
                denom = np.expm1(k2)
                # denom 极小理论上已被 small 排除，但加一点保护
                denom[np.abs(denom) < 1e-12] = 1e-12
                out[mask] = np.expm1(k2 * t2) / denom

            return out

        elif mode == "logistic":
            # logistic：支持标量 k 或数组 k，k 控制陡峭程度
            t_arr = t
            s_arr = np.asarray(k, float)
            try:
                s_arr = np.broadcast_to(s_arr, t_arr.shape)
            except ValueError:
                raise ValueError("logistic 模式下 k 的形状无法与 t 广播匹配")

            v0 = 1.0 / (1.0 + np.exp(0.5 * s_arr))
            v1 = 1.0 / (1.0 + np.exp(-0.5 * s_arr))
            denom = v1 - v0

            out = np.empty_like(t_arr, float)

            # denom 很小 → logistic 退化为线性
            small = np.abs(denom) < 1e-12
            if np.any(small):
                out[small] = t_arr[small]

            mask = ~small
            if np.any(mask):
                s2 = s_arr[mask]
                t2 = t_arr[mask]
                v0_2 = v0[mask]
                denom2 = denom[mask]
                yv = 1.0 / (1.0 + np.exp(-s2 * (t2 - 0.5)))
                out[mask] = (yv - v0_2) / denom2

            return out

        elif mode == "cos":
            # 平滑余弦（0→1 单调）
            return 0.5 - 0.5 * np.cos(np.pi * t)

        elif mode == "sin":
            # 半周期正弦（0→1 单调）
            return np.sin(np.pi * t / 2)

        elif mode == "poly2":
            # 二次缓入缓出
            return t * (2 - t)

        elif mode == "poly3":
            # 三次 smoothstep
            return t ** 2 * (3 - 2 * t)

        else:
            raise ValueError(f"未知 mode: {mode}")

    # --------------------------------------------------------
    #  2. 单段的“代价函数”：越小表示越平滑、越符合全局趋势
    # --------------------------------------------------------
    def _segment_cost(
        self,
        mode: str,
        k: float,
        y0: float,
        y1: float,
        span: float,
        s_left: float,
        s_right: float,
    ) -> float:
        """
        评估某一段 [x_i, x_{i+1}] 采用给定 (mode, k) 后的“代价”。

        目标：
        - 段首尾斜率尽量贴合全局预估斜率（s_left, s_right）
        - 段内斜率尽量平滑（不抖、不突变）
        - 尊重整体单调性约束（auto_monotonic）
        """
        if span < 1e-12:
            # 极短区间直接认为代价巨大，不采用
            return 1e9

        dy = y1 - y0
        t_eps = 1e-3  # 用于近似数值微分

        def dy_dx_at(t0: float) -> float:
            # 数值微分：在 t0 附近求 dr/dt，再换算成 dy/dx
            t1 = np.clip(t0 + t_eps, 0.0, 1.0)
            t2 = np.clip(t0 - t_eps, 0.0, 1.0)
            r1 = self._curve_ratio(np.array([t1]), mode, k)[0]
            r2 = self._curve_ratio(np.array([t2]), mode, k)[0]
            dr_dt = (r1 - r2) / (t1 - t2 + 1e-12)
            return dy / span * dr_dt

        # 段首 / 段尾斜率
        dy0 = dy_dx_at(0.0)
        dy1 = dy_dx_at(1.0)

        cost = 0.0

        # ① 斜率贴合全局估计 (auto_smooth)
        if s_left is not None:
            cost += (dy0 - s_left) ** 2
        if s_right is not None:
            cost += (dy1 - s_right) ** 2

        # ② 段内斜率平滑（不出现剧烈跳变）
        cost += 0.1 * (dy1 - dy0) ** 2

        # ③ 在小变化下，惩罚过于“激烈”的模型（exp / logistic 等）
        change_ratio = abs(dy) / (abs(y0) + 1e-9)
        if mode in ("exp", "logistic") and change_ratio < 0.2:
            cost *= 1.5

        # ④ 单调性约束 (auto_monotonic)
        if self._monotonic_dir != 0:
            # 预期整体斜率符号
            if self._monotonic_dir > 0:
                # 期望整体递增：若某段首尾斜率为负则大罚
                if dy0 < -1e-9 or dy1 < -1e-9:
                    cost += 1e6
            else:
                # 期望整体递减：若某段首尾斜率为正则大罚
                if dy0 > 1e-9 or dy1 > 1e-9:
                    cost += 1e6

        return float(cost)

    # --------------------------------------------------------
    #  3. 为单段选择 (mode, k) 的最佳组合（auto 核心）
    # --------------------------------------------------------
    def _choose_best_segment(
        self,
        i: int,
        y0: float,
        y1: float,
        span: float,
    ) -> Tuple[str, float]:
        """
        对第 i 段 [x_i, x_{i+1}]，在若干候选 (mode, k) 中选择代价最小的组合。
        """
        # 当前段两端的“目标斜率”（来自全局估计）
        s_left = self._slopes[i]
        s_right = self._slopes[i + 1]

        # 候选模式 + 候选 k 列表（可按需求继续扩展）
        candidates = {
            "linear":   [1.0],                        # 无 k，用 1.0 占位
            "power":    [0.5, 0.8, 1.0, 1.2, 1.5, 2.0],
            "exp":      [0.5, 1.0, 1.5, 2.0],
            "logistic": [2.0, 4.0, 6.0],
            "poly3":    [1.0],                        # 无 k，用 1.0 占位
        }

        # 若该段变化极小，直接用线性，避免数值抖动
        dy = y1 - y0
        change_ratio = abs(dy) / (abs(y0) + 1e-9)
        if change_ratio < 0.05:
            return "linear", 1.0

        best_mode = "linear"
        best_k = 1.0
        best_cost = float("inf")

        for mode, k_list in candidates.items():
            for k in k_list:
                c = self._segment_cost(mode, k, y0, y1, span, s_left, s_right)
                if c < best_cost:
                    best_cost = c
                    best_mode = mode
                    best_k = k

        return best_mode, best_k

    # --------------------------------------------------------
    #  4. 自动分段 & 自动选择 (mode, k)（带缓存）
    # --------------------------------------------------------
    def _auto_segments(self):
        """
        为每一段 [x_i, x_{i+1}] 自动选择 (mode, k)，结果做缓存。
        """
        if self._auto_segments_cache is not None:
            return self._auto_segments_cache

        x, y = self.x, self.y
        segs = []
        for i in range(len(x) - 1):
            y0, y1 = y[i], y[i + 1]
            span = x[i + 1] - x[i]
            mode_i, k_i = self._choose_best_segment(i, y0, y1, span)
            segs.append({"mode": mode_i, "k": k_i})

        self._auto_segments_cache = segs
        return segs

    # --------------------------------------------------------
    #  5. 顶层调用：插值 + 外推
    # --------------------------------------------------------
    def __call__(
        self,
        new_x: ArrayLike,
        mode: str = "auto",
        k: float = 1.0,
        segments=None,
        extrapolate: str = "edge",
    ):
        """
        对给定 new_x 进行插值 + 外推。
        """
        new_x = np.asarray(new_x, float)
        flat = new_x.ravel()
        result = np.empty_like(flat)

        x0, x1 = self.x[0], self.x[-1]
        inside = (flat >= x0) & (flat <= x1)  # 插值区间内
        left = flat < x0                      # 左侧外推
        right = flat > x1                     # 右侧外推

        # ========= 内插部分 =========
        if np.any(inside):
            x_in = flat[inside]
            if segments is not None:
                # 手动分段
                result[inside] = self._multi_segment(x_in, segments)
            elif mode != "auto":
                # 单段 + 指定 mode
                result[inside] = self._single_segment(x_in, mode, k)
            else:
                # auto 模式：单段 / 多段智能判断
                if self.n == 2:
                    # 只有两个点：仍然走“最佳段选择”逻辑
                    span = self.x[1] - self.x[0]
                    mode_auto, k_auto = self._choose_best_segment(
                        0, self.y[0], self.y[1], span
                    )
                    result[inside] = self._single_segment(x_in, mode_auto, k_auto)
                else:
                    # 多点：全自动多段拟合
                    auto_segs = self._auto_segments()
                    result[inside] = self._multi_segment(x_in, auto_segs)

        # ========= 外推部分 =========
        if np.any(left):
            result[left] = self._auto_extrap(flat[left], "left", extrapolate)
        if np.any(right):
            result[right] = self._auto_extrap(flat[right], "right", extrapolate)

        return result.reshape(new_x.shape)

    # --------------------------------------------------------
    #  6. 单段插值（使用首尾两点）
    # --------------------------------------------------------
    def _single_segment(self, new_x: np.ndarray, mode: str, k: float) -> np.ndarray:
        x0, x1 = self.x[0], self.x[-1]
        y0, y1 = self.y[0], self.y[-1]

        span = x1 - x0
        if span < 1e-12:
            return np.full_like(new_x, y0)

        t = np.clip((new_x - x0) / span, 0, 1)
        ratio = self._curve_ratio(t, mode, k)
        return y0 + (y1 - y0) * ratio

    # --------------------------------------------------------
    #  7. 多段插值（支持自动 / 手动 segments，带缓存）
    # --------------------------------------------------------
    def _multi_segment(self, new_x: np.ndarray, segments):
        x, y = self.x, self.y
        nseg = len(x) - 1

        # 找到每个 new_x 所在的段 index：x[i] <= new_x < x[i+1]
        idx = np.searchsorted(x, new_x, side="right") - 1
        idx = np.clip(idx, 0, nseg - 1)

        x0 = x[idx]
        x1 = x[idx + 1]
        y0 = y[idx]
        y1 = y[idx + 1]

        # —— segments 缓存（支持不同 segments 多次调用）——
        seg_id = id(segments)
        if self._seg_cache_id != seg_id:
            self._seg_modes_cached = np.array([s["mode"] for s in segments])
            self._seg_ks_cached = np.array([s.get("k", 1.0) for s in segments], float)
            self._seg_cache_id = seg_id

        mode_arr = self._seg_modes_cached[idx]
        k_arr = self._seg_ks_cached[idx]

        span = x1 - x0
        span[span < 1e-12] = 1.0  # 避免除零

        t = np.clip((new_x - x0) / span, 0, 1)

        ratio = np.zeros_like(t)
        for m in np.unique(mode_arr):
            mask = (mode_arr == m)
            ratio[mask] = self._curve_ratio(t[mask], m, k_arr[mask])

        return y0 + (y1 - y0) * ratio

    # --------------------------------------------------------
    #  8. 自动外推：auto → 组合策略；非 auto → 指定策略
    # --------------------------------------------------------
    def _auto_extrap(self, new_x: np.ndarray, side: str, method: str) -> np.ndarray:
        """
        自动外推逻辑：
    
        - 若 method != "auto"：直接尝试对应外推方式，失败则退化为 "linear"
        - 若 method == "auto"：
            依次尝试 ["linear", "power", "exp", "mirror"]，
            任一成功即返回，全部失败时退化为 "edge"
        """   
        if method != "auto":
            try:
                return self._manual_extrap(new_x, side, method)
            except Exception:
                # 用户指定方法失败时，退化为 linear 更安全
                return self._manual_extrap(new_x, side, "linear")

        # Auto 策略：先最稳的，再“物理感”更强的
        for m in ["linear", "power", "exp", "mirror"]:
            try:
                return self._manual_extrap(new_x, side, m)
            except Exception:
                continue

        # 最终兜底：edge
        return self._manual_extrap(new_x, side, "edge")

    # --------------------------------------------------------
    #  9. 外推实现（edge / linear / exp / power / mirror）
    # --------------------------------------------------------
    def _manual_extrap(self, new_x: np.ndarray, side: str, method: str) -> np.ndarray:
        x, y = self.x, self.y

        idx0, idx1 = (0, 1) if side == "left" else (-2, -1)
        x0, x1 = x[idx0], x[idx1]
        y0, y1 = y[idx0], y[idx1]

        if method == "edge":
            return np.full_like(new_x, y0 if side == "left" else y1)

        if method == "mirror":
            # 以边界为“镜面”，反射内部斜率
            slope = (y1 - y0) / (x1 - x0)
            if side == "left":
                d = x0 - new_x
                return y0 + slope * d
            else:
                d = new_x - x1
                return y1 - slope * d

        if method == "linear":
            slope = (y1 - y0) / (x1 - x0)
            ref_x, ref_y = (x0, y0) if side == "left" else (x1, y1)
            return ref_y + slope * (new_x - ref_x)

        if method == "exp":
            if y0 <= 0 or y1 <= 0:
                raise ValueError("exp 外推需 y>0")
            k = np.log(y1 / y0) / (x1 - x0)
            if side == "left":
                return y0 * np.exp(k * (new_x - x0))
            return y1 * np.exp(k * (new_x - x1))

        if method == "power":
            if x0 <= 0 or x1 <= 0 or y0 <= 0 or y1 <= 0:
                raise ValueError("power 外推需 x,y>0")
            p = np.log(y1 / y0) / np.log(x1 / x0)
            if side == "left":
                return y0 * (new_x / x0) ** p
            return y1 * (new_x / x1) ** p

        raise ValueError(f"未知外推方式：{method}")


# ============================================================
#  顶层一句话接口：interp_curve(...)
#  —— 推荐对外只用这个函数 —— 
# ============================================================
def interp_curve(
    x: ArrayLike = None,
    y: ArrayLike = None,
    new_x: ArrayLike = None,
    *,  # * 之后的变量全部为关键字传参
    start: float = None,
    end: float = None,
    num: int = None,
    mode: str = "auto",
    k: float = 1.0,
    segments=None,  # 手动多段时才需要的参数，指定每一段的插值模式与k值，没有k则不填写
    extrapolate: str = "edge",
):
    """
    一句话完成插值 + 外推（extrapolation）+ 曲线演化（curve evolution）。

    interp_curve 是对 CurveInterpolator 的顶层封装：
    - 自动判断采用单段 / 多段方式
    - 自动处理插值 / 外推
    - 高度灵活，同时保持统一一致的接口形式

    使用场景
    --------
    1) 基于原始节点 (x, y)，对 new_x 进行插值或外推：
        interp_curve(x, y, new_x, mode="auto", extrapolate="auto")

    2) 生成一条“从 start 平滑过渡到 end”的曲线：
        interp_curve(start=100, end=40, num=50, mode="logistic")

    参数
    ----
    x, y : array-like
        原始数据点坐标。
        - x：自变量（如年份、时间、容量等）
        - y：因变量，与 x 一一对应
        - 要求 len(x) == len(y) 且不少于 2 个点
        - 若提供 start/end/num，则忽略 x,y,new_x

    new_x : array-like
        需要插值 / 外推的自变量点。
        - 可为标量、列表、ndarray，或任意形状数组
        - 返回数组将保持与 new_x 完全相同的形状

    start, end, num : float/int, optional
        单段插值模式（不依赖 x/y）：
            x = [0, 1]
            y = [start, end]
            new_x = linspace(0, 1, num)
        适用于创建平滑“趋势线”或“调节曲线”。

    mode : str, default "auto"
        插值模式（内部插值部分）。分为两类：

        A. 智能模式：
            "auto"  
                - 若只有 2 个点：自动选择最佳单段 (mode, k)
                - 若超过 2 个点：自动为每段选择模式和形状参数 k

        B. 手动模式：
            "linear"   : 线性
            "power"    : 幂函数曲线
            "exp"      : 指数曲线
            "logistic" : S 型曲线
            "sin"      : 正弦缓出
            "cos"      : 余弦缓入缓出
            "poly2"    : 二次缓入缓出
            "poly3"    : 三次 smoothstep

        注意：
        - 若 segments 不为 None，则忽略 mode（完全按 segments 分段）

    k : float, default 1.0
        形状参数，仅用于以下模式：
        - power   ：k<1 “先快后慢”，k>1 “先慢后快”
        - exp     ：指数强度
        - logistic：S 型陡峭程度

    segments : list 或 None
        手动定义多段插值方式。
        - 长度必须为 len(x) - 1
        - 每段为 {"mode": ..., "k": ...} 的字典
        - 若为 None，则：
            mode="auto" → 自动多段拟合
            mode!="auto" → 单段插值（只用首尾两点）

    extrapolate : str, default "edge"
        外推方式（new_x 落在 x 之外时的处理）：

        - "edge"   : 使用边界值常数外推（最稳妥）
        - "linear" : 使用边界斜率线性延伸
        - "exp"    : 指数外推（需 y>0）
        - "power"  : 幂律外推（需 x>0 且 y>0）
        - "mirror" : “镜面反射”外推（更强调趋势）
        - "auto"   : 智能外推：
                        依次尝试 ["linear", "power", "exp", "mirror"]
                        若均失败，则退化到 "edge"

    返回
    ----
    values : np.ndarray
        与 new_x 形状完全一致的结果数组。
        数组中既包含插值结果，也包含必要的外推值。

    异常
    ----
    ValueError：
        - 若未提供 (x,y,new_x) 且未提供 (start,end,num)
        - 若 x/y 长度不一致
        - 若有效点数量不足 2
    """
    
    # ==== 单段：start / end / num 调用形式 ====
    if start is not None and end is not None and num is not None:
        x = [0.0, 1.0]
        y = [start, end]
        new_x = np.linspace(0.0, 1.0, int(num))

    # ==== 检查输入合法性 ====
    if x is None or y is None or new_x is None:
        raise ValueError("必须提供 (x, y, new_x) 或 (start, end, num)")

    interp = CurveInterpolator(x, y)
    return interp(new_x, mode=mode, k=k, segments=segments, extrapolate=extrapolate)


# ============================================================
#  批量插值：batch_interp_curve（公共 x/new_x）
# ============================================================
def batch_interp_curve(
    data: Dict[str, Dict[str, Any]],
    *,
    common_x: ArrayLike = None,
    common_new_x: ArrayLike = None,
    start: float = None,
    end: float = None,
    num: int = None,
    mode: str = "auto",
    k: float = 1.0,
    segments=None,
    extrapolate: str = "edge",
):
    """
    批量插值多个“类别”（category），适用于多个序列需要统一或分组插值的场景。
    支持多点插值、单段插值、手动分段、多模式插值等全部功能，外层行为与
    interp_curve 完全一致，扩展为批量处理能力。

    功能特性
    --------
    1. 每个类别可独立指定：
       - 自己的 x / y / new_x（多点插值）
       - 或使用 start / end / num（单段插值）
       - 或继承批量级 common_x / common_new_x

    2. 每个类别可单独配置插值控制项：
       - mode（插值模式）
       - k（形状参数）
       - segments（手动分段）
       - extrapolate（外推方式）

    3. 若某类别未提供自己的配置，则自动继承批量级参数。

    4. 完全兼容 interp_curve 的全部参数形式（single/multi segment, auto 模式等）。

    参数
    ----
    data : dict
        批量插值的数据结构，应为如下格式的字典：

        {
            类别名1: {
                # === 方式 A：多点插值（x/y/new_x） ===
                "x": [...],          # 可为空（继承 common_x）
                "y": [...],          # 必须
                "new_x": [...],      # 可为空（继承 common_new_x）

                # === 方式 B：单段插值（start/end/num） ===
                "start": 0,
                "end": 10,
                "num": 100,

                # === 插值控制项 ===
                "mode": "linear",
                "k": 1.2,
                "segments": [...],
                "extrapolate": "power",
            },

            类别名2: {...},
            ...
        }

    common_x : array-like, optional
        批量级公共自变量序列。若类别未提供 x，则该类别使用 common_x。

    common_new_x : array-like, optional
        批量级公共插值点序列。若类别未提供 new_x，则该类别使用 common_new_x。

    start, end, num : float or int, optional
        批量级单段插值快捷方式。
        若某类别自己提供 start/end/num，则优先级高于批量级设置。
        使用单段插值时，该类别不再需要 x/y/new_x。

    mode : str, default "auto"
        批量级插值模式（类别可覆盖）。

    k : float, default 1.0
        批量级形状控制参数（类别可覆盖）。

    segments : list or None
        批量级手动分段控制（类别可覆盖）。
        每个元素应为 {"mode": ..., "k": ...} 的字典。

    extrapolate : str, default "edge"
        批量级外推方式（类别可覆盖）。
        可选：edge / linear / exp / power / mirror / auto。

    返回
    ----
    results : dict
        返回字典，其键为类别名，值为对应类别的插值结果（np.ndarray）：

        {
            类别名1: np.ndarray([...]),
            类别名2: np.ndarray([...]),
            ...
        }

        返回数组的 shape 与该类别实际使用的 new_x 相同。

    优先级规则（从高到低）
    --------------------
    1. 类别内部参数
    2. 批量级参数
    3. 公共 common_x / common_new_x
    4. interp_curve 默认参数

    使用说明
    --------
    batch_interp_curve 可在以下场景中大幅提高效率：
    - 能源系统规划（多区域多技术插值）
    - 多情景仿真（批量处理不同参数）
    - 经济模型（多个序列共享插值点）
    - 批量曲线平滑、外推、多段拟合等

    同时支持：
    - 智能模式（auto）
    - 手动多段模式（segments）
    - 单段/多点插值混合使用
    - 外推方式任意组合

    函数会自动判断每个类别应当使用哪种插值方式，
    并保证批量行为与单类别 interp_curve 保持完全一致。
    """

    # ==================================================================
    # A) 参数合法性检查
    # ==================================================================
    if not isinstance(data, dict):
        raise TypeError("data 必须为 dict，格式为 {类别: 配置dict}。")

    if segments is not None and not isinstance(segments, (list, tuple)):
        raise TypeError("segments 必须为 list 或 tuple。")

    # ==================================================================
    # B) 转换公共 common_x / common_new_x
    # ==================================================================
    x_common = np.asarray(common_x, float) if common_x is not None else None
    new_x_common = np.asarray(common_new_x, float) if common_new_x is not None else None

    results = {}

    # ==================================================================
    # 主循环
    # ==================================================================
    for category, cfg in data.items():

        if not isinstance(cfg, dict):
            raise TypeError(f"类别 {category} 的配置必须是 dict。")

        # --------------------------------------------------------------
        # 1) 单段插值 (start/end/num)
        # --------------------------------------------------------------
        start_used = cfg.get("start", start)
        end_used   = cfg.get("end", end)
        num_used   = cfg.get("num", num)

        if start_used is not None and end_used is not None and num_used is not None:

            seg_used = cfg.get("segments", segments)

            results[category] = interp_curve(
                start=start_used,
                end=end_used,
                num=int(num_used),
                mode=cfg.get("mode", mode),
                k=cfg.get("k", k),
                segments=seg_used,
                extrapolate=cfg.get("extrapolate", extrapolate),
            )
            continue

        # --------------------------------------------------------------
        # 2) 多点插值 (x/y/new_x)
        # --------------------------------------------------------------

        # x：类别 > 公共 common_x
        if "x" in cfg and cfg["x"] is not None:
            x_used = np.asarray(cfg["x"], float)
        else:
            if x_common is None:
                raise ValueError(f"类别 {category} 缺少 x，且无公共 common_x")
            x_used = x_common

        # y 必须
        if "y" not in cfg:
            raise ValueError(f"类别 {category} 缺少 y 数据")
        y_used = np.asarray(cfg["y"], float)

        if len(x_used) != len(y_used):
            raise ValueError(
                f"类别 {category} 的 x 与 y 长度不一致：len(x)={len(x_used)}, len(y)={len(y_used)}"
            )

        # new_x：类别 > 公共 common_new_x
        if "new_x" in cfg and cfg["new_x"] is not None:
            new_x_used = np.asarray(cfg["new_x"], float)
        else:
            if new_x_common is None:
                raise ValueError(f"类别 {category} 缺少 new_x，且无公共 common_new_x")
            new_x_used = new_x_common

        # --------------------------------------------------------------
        # 3) mode/k/segments/extrapolate 选择逻辑
        # --------------------------------------------------------------
        mode_used        = cfg.get("mode", mode)
        k_used           = cfg.get("k", k)
        extrapolate_used = cfg.get("extrapolate", extrapolate)

        segments_used = cfg.get("segments", segments)

        # --------------------------------------------------------------
        # 4) 调用 interp_curve（核心）
        # --------------------------------------------------------------
        results[category] = interp_curve(
            x=x_used,
            y=y_used,
            new_x=new_x_used,
            mode=mode_used,
            k=k_used,
            segments=segments_used,
            extrapolate=extrapolate_used,
        )

    return results
