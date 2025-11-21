import numpy as np
import matplotlib.pyplot as plt
import safeinterp as si

x = [0, 10, 20]
y = [0, 5, 30]

new_x = np.linspace(0, 20, 200)
result = si.interp_curve(x, y, new_x, mode="auto")

plt.figure(figsize=(6,4))
plt.plot(x, y, "o", label="Data points")
plt.plot(new_x, result, label="Interpolated curve")
plt.title("Basic interpolation example (mode='auto')")
plt.legend()
plt.grid(True)
plt.show()
