import numpy as np
import pandas as pd

from run import check_missing_slices


def test_image_type_nan():
    df_dict = {'ImageType': (['test'] * 8).extend([np.NaN, 'LOCALIZER']), 'SliceLocation': [x for x in range(10)]}
    df = pd.DataFrame(df_dict)
    check_missing_slices(df, 'SliceLocation')
