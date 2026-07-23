from python_magnetrun.MagnetRun import load_mrun

# Just provide the filename - it searches automatically!
mrun = load_mrun("data/M9_2019.02.14---23_00_38.txt", housing="M9")
print(f"Loaded: {mrun.MagnetData.FileName}")
print(f"StartTime: {mrun.StartTime}")

mdata = mrun.getMData()
print(type(mdata))
data = mdata.Data
print(data.head())


