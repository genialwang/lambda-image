################################
# Author   : septicmk
# Date     : 2015/07/29 10:36:05
# FileName : segmentation.py
################################

from MEHI.utils.tool import exeTime
import numpy as np

def threshold(rdd, method='adaptive', *args):
    from skimage.filters import threshold_otsu, threshold_adaptive
    import scipy.ndimage as ndi
    def adaptive(frame):
        binary = threshold_adaptive(frame, block_size=block_size)
        #binary = ndi.binary_fill_holes(binary)
        return binary
    def otsu(frame):
        threshold = threshold_otsu(frame)
        binary = frame > threshold
        return binary
    def duel(frame):
        threshold = threshold_otsu(frame)
        binary1 = frame > threshold
        tframe = frame - binary1 * frame
        frame = tframe + binary1 * frame * max(tframe.flatten())/max(frame.flatten())
        threshold = threshold_otsu(frame)
        binary2 = frame > threshold
        binary = binary2
        return binary
    if method=='adaptive':
        block_size = args[0]
        return rdd.applyValues(adaptive)
    elif method == 'otsu':
        return rdd.applyValues(otsu)
    elif method == 'duel':
        return rdd.applyValues(duel)
    else:
        raise "Bad Threshold Method", method

def peak_filter(rdd, smooth_size):
    from skimage.morphology import binary_opening
    def func(frame):
        opened = binary_opening(frame, disk(smooth_size))
        opened = opened & frame
        return opened
    return rdd.applyValues(func)

@exeTime
def watershed_3d(image_stack, binary, min_distance=10, min_radius=6):
    from skimage.morphology import watershed, remove_small_objects
    from scipy import ndimage
    from skimage.feature import peak_local_max
    binary = remove_small_objects(binary, min_radius, connectivity=3)
    distance = ndimage.distance_transform_edt(binary)
    local_maxi = peak_local_max(distance, min_distance=min_distance, indices=False, labels=image_stack)
    markers = ndimage.label(local_maxi)[0]
    labeled_stack = watershed(-distance, markers, mask=binary)
    return labeled_stack

@exeTime
def properties(labeled_stack):
    from MEHI.udf._moment import moment
    from scipy import ndimage as ndi
    import pandas as pd
    labeled_stack = np.squeeze(labeled_stack)
    prop = []
    columns = ('x', 'y', 'z', 'volume')
    indices = []
    label = 0
    objects = ndi.find_objects(labeled_stack)
    for i, _slice in enumerate(objects):
        if _slice is None:
            continue
        label += 1
        mu = moment(labeled_stack[_slice].astype(np.double))
        volume = mu[0]
        x = mu[1] + _slice[0].start
        y = mu[2] + _slice[1].start
        y = mu[3] + _slice[2].start
        prop.append([x,y,z,volume])
        indices.append(label)
    indices = pd.Index(indices, name='label')
    prop = pd.DataFrame(prop, index=indices, columns=columns)
    return prop

if __name__ == "__main__":
    pass
