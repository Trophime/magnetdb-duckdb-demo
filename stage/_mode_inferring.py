from _common import *




def main():

    mrun = MagnetRun.fromtdms(housing = "M10", site = "M10", filename = str(PIGBROTHER))
    mdata = mrun.getMData()
<<<<<<< HEAD
    df = mdata.Data["Courants_Alimentations"]

    print("\nAvailable channels:", df.columns)

    IH, IB = df["Courant_GR1"], df["Courant_GR2"]
    
    plt.figure(figsize = (10, 6))
    plt.plot(df["Courant_GR1"], label = "Current GR1")
    plt.plot(df["Courant_GR2"], label = "Current GR2")
    plt.plot(df["Référence_GR1"], ":", label = "Reference GR1")
    plt.plot(df["Référence_GR2"], ":",  label = "Reference GR2")
    plt.legend()
    plt.grid(True)
    plt.savefig("courant_vs_reference_comparison.png", dpi = 500)

    t = np.arange(len(df))
    plt.figure(figsize = (10, 6))
    plt.scatter(IH, IB, c = t, s = 1)
    plt.xlabel("Référence_GR1")
    plt.ylabel("Référence_GR2")
    plt.colorbar(label = "time")
    plt.grid(True)
    plt.savefig("IH_IB_relation.png", dpi = 500)
=======
    print(mdata)

    print(mdata.Data["Courants_Alimentations"].columns)
>>>>>>> fb9d561 (feat: refactor housing summary pipeline)




if __name__ == "__main__":

    main()