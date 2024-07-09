import seaborn as sns
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt


def scatter_attributes(df, *, attributes=[], labels=[], hue=None):
    """Plots a reduced Seaborn PairGrid scatter plot of attributes against the labels.

    Arguments:
    df -- DataFrame containing the attributes and labels in tidy format.
    attributes -- List of strings identifying attribute columns in df.
    labels -- List of strings identifying label columns in df.
    """

    g = sns.PairGrid(
        df,
        x_vars=attributes,
        y_vars=labels,
        hue=hue,
        palette="Blues")
    g = g.map(plt.scatter)

    return g
