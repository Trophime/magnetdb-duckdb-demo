from _common import *




IB_ZERO_THRESHOLD = 50
IH_ZERO_THRESHOLD = 50

def infer_mode(IH, IB):

    mask = np.isfinite(IH) & np.isfinite(IB)
    IH, IB = IH[mask], IB[mask]

    FIT_MAX_CURRENT = 0.25 * np.nanmax(IB)

    if len(IH) == 0:
        return "UNKNOWN", np.nan, np.nan
    if np.nanmax(np.abs(IH)) < IH_ZERO_THRESHOLD:
        return "NORMAL", 0.0, np.nan
    if np.nanmax(np.abs(IB)) < IB_ZERO_THRESHOLD:
        return "NORMAL", np.inf, np.nan

    fit_mask = (IB_ZERO_THRESHOLD < IB) & (IB < FIT_MAX_CURRENT)
    if fit_mask.sum() < 10:
        fit_mask = IB > IB_ZERO_THRESHOLD

    x, y = IB[fit_mask], IH[fit_mask]

    if len(x) < 2:
        return "UNKNOWN", np.nan, np.nan

    slope, shift = np.polyfit(x, y, 1)

    if 0.66 <= slope <= 1.5:
        mode = "NORMAL"
    else:
        mode = "ECO"

    return mode, slope, shift, FIT_MAX_CURRENT


def main():

    mrun = MagnetRun.fromtdms(housing = "M10", site = "M10", filename = str(PIGBROTHER))
    mdata = mrun.getMData()
    df = mdata.Data["Courants_Alimentations"]

    print("\nAvailable channels:", df.columns)

    IH,   IB   = df["Courant_GR1"],   df["Courant_GR2"]
    RefH, RefB = df["Référence_GR1"], df["Référence_GR2"]

    # Current vs Reference comparison

    plt.figure(figsize = (10, 6))
    plt.plot(IH, label = "Current GR1")
    plt.plot(IB, label = "Current GR2")
    plt.plot(RefH, ":", label = "Reference GR1")
    plt.plot(RefB, ":", label = "Reference GR2")
    plt.legend()
    plt.grid(True)
    plt.savefig("courant_vs_reference_comparison.png", dpi = 500)
    plt.close()

    # Infer mode computation

    mode, slope, shift, FIT_MAX_CURRENT = infer_mode(IH, IB)
    print(f"Fit interval: {IB_ZERO_THRESHOLD:.0f} - {FIT_MAX_CURRENT:.0f} A")
    print(f"\nSlope: {slope:.3f}")
    print(f"Shift: {shift:.3f}")
    print(f"Mode: {mode}")
    print(f"IH = {slope:.3f} x IB + {shift:.3f}")

    # IH vs IB scatter plot

    xfit = np.linspace(IB_ZERO_THRESHOLD, FIT_MAX_CURRENT, 100)
    t = np.arange(len(df))
    plt.figure(figsize = (10, 6))
    plt.scatter(IB, IH, c = t, s = 1, cmap = "viridis", label = "Measurements")
    plt.plot(xfit, slope * xfit + shift, linewidth = 2, label = f"Fit (slope = {slope:.3f})")
    plt.xlabel("IB")
    plt.ylabel("IH")
    plt.legend()
    plt.grid(True)
    plt.savefig("IH_vs_IB.png", dpi = 500)
    plt.close()



if __name__ == "__main__":

    main()