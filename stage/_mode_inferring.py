from _common import *




def main():

    mrun = MagnetRun.fromtdms(housing = "M10", site = "M10", filename = str(PIGBROTHER))
    mdata = mrun.getMData()
    print(mdata)

    print(mdata.Data["Courants_Alimentations"].columns)




if __name__ == "__main__":

    main()