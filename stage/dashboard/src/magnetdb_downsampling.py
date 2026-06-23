import plotly.graph_objects as go

fig = go.Figure()


def naive_downsampling(df, x_col, y_col, max_points=1000):
    """
    Downsample the DataFrame by selecting every nth point based on the max_points limit.
    
    Parameters:
    - df: pandas DataFrame containing the data
    - x_col: name of the column to be used for the x-axis
    - y_col: name of the column to be used for the y-axis
    - max_points: maximum number of points to retain after downsampling
    
    Returns:
    - downsampled_df: pandas DataFrame after downsampling
    """
    if len(df) <= max_points:
        return df  # No downsampling needed

    step = len(df) // max_points
    downsampled_df = df.iloc[::step, :].copy()
    
    return downsampled_df