"""Classes relating to BlockingStrategies, which define ways to carve up Images into Blocks.
"""
import bisect
import itertools
from numpy import expand_dims, zeros
from numpy import dtype as dtypeFunc

from lambdaimage.rdds.imgblocks.blocks import BlockGroupingKey, Blocks, PaddedBlockGroupingKey, PaddedBlocks, \
    SimpleBlocks, getStartStopStep
from lambdaimage.utils.common import selectByMatchingPrefix


class BlockingStrategy(object):
    """Superclass for objects that define ways to split up images into smaller blocks.
    """

    # max block size that we will produce from images without printing a warning
    # TODO make configurable?
    DEFAULT_MAX_BLOCK_SIZE = 500000000  # 500 MB

    def __init__(self):
        self._dims = None
        self._nimages = None
        self._dtype = None

    @property
    def dims(self):
        """Shape of the Images data to which this BlockingStrategy is to be applied.

        dims will be taken from the Images passed in the last call to setSource().

        n-tuple of positive int, or None if setSource has not been called
        """
        return self._dims

    @property
    def nimages(self):
        """Number of images (time points) in the Images data to which this BlockingStrategy is to be applied.

        nimages will be taken from the Images passed in the last call to setSource().

        positive int, or None if setSource has not been called
        """
        return self._nimages

    @property
    def dtype(self):
        """Numpy data type of the Data object to which this BlockingStrategy is to be applied.

        String of numpy dtype spec, or None if setSource has not been called
        """
        return self._dtype

    def setSource(self, source):
        """Readies the BlockingStrategy to operate over the passed object.

        dims, nimages, and dtype should be initialized by this call.

        Subclasses should override this implementation to set self.nimages; this implementation
        sets only self.dims and self.dtype.

        No return value.
        """
        self._dims = _normDimsToShapeTuple(source.dims)
        self._dtype = str(source.dtype)

    def getBlocksClass(self):
        """Get the subtype of Blocks that instances of this strategy will produce.

        Subclasses should override this method to return the appropriate Blocks subclass.
        """
        return Blocks

    def calcAverageBlockSize(self):
        """Calculates the estimated average block size in bytes for this strategy applied to the Images
        last passed to setSource.

        Returns
        -------
        float block size in bytes
        """
        raise NotImplementedError("calcAverageBlockSize not implemented")

    def blockingFunction(self, timePointIdxAndImageArray):
        raise NotImplementedError("blockingFunction not implemented")

    def combiningFunction(self, spatialIdxAndBlocksSequence):
        raise NotImplementedError("combiningFunction not implemented")


class SimpleBlockingStrategy(BlockingStrategy):
    """A BlockingStrategy that groups Images into nonoverlapping, roughly equally-sized blocks.

    The number and dimensions of image blocks are specified as "splits per dimension", which is for each
    spatial dimension of the original Images the number of partitions to generate along that dimension. So
    for instance, given a 12 x 12 Images object, a SimpleBlockingStrategy with splitsPerDim=(2,2)
    would yield Blocks objects with 4 blocks, each 6 x 6.
    """
    VALID_UNITS = frozenset(["pixels", "splits"])

    def __init__(self, unitsPerDim, units="pixels", **kwargs):
        """Returns a new SimpleBlockingStrategy.

        Parameters
        ----------
        splitsPerDim : n-tuple of positive int, where n = dimensionality of image
            Specifies that intermediate blocks are to be generated by splitting the i-th dimension
            of the image into splitsPerDim[i] roughly equally-sized partitions.
            1 <= splitsPerDim[i] <= self.dims[i]
        """
        super(SimpleBlockingStrategy, self).__init__()
        try:
            units = selectByMatchingPrefix(units, SimpleBlockingStrategy.VALID_UNITS)
        except IndexError:
            raise ValueError("No valid units match prefix '%s'. Valid choices are: %s" %
                             (units, SimpleBlockingStrategy.VALID_UNITS))
        unitsPerDim = SimpleBlockingStrategy.normalizeUnitsPerDim(unitsPerDim)
        if units == "pixels":
            self._pixPerDim = unitsPerDim
            self._splitsPerDim = None
        else:
            self._pixPerDim = None
            self._splitsPerDim = unitsPerDim
        self._slices = None

    @property
    def splitsPerDim(self):
        return self._splitsPerDim

    @property
    def pixelsPerDim(self):
        return self._pixPerDim

    def getBlocksClass(self):
        return SimpleBlocks

    @classmethod
    def generateFromBlockSize(cls, images, blockSize, **kwargs):
        """Returns a new SimpleBlockingStrategy, that yields blocks
        closely matching the requested size in bytes.

        Parameters
        ----------
        images : Images object
            Images for which blocking strategy is to be generated.

        blockSize : positive int or string
            Requests an average size for the intermediate blocks in bytes. A passed string should
            be in a format like "256k" or "150M" (see util.common.parseMemoryString). If blocksPerDim
            or groupingDim are passed, they will take precedence over this argument. See
            strategy._BlockMemoryAsSequence for a description of the blocking strategy used.

        Returns
        -------
        SimpleBlockingStrategy or subclass
            new BlockingStrategy will be created and setSource() called on it with the passed images object
        """
        dims, nimages, dtype = images.dims, images.nrecords, images.dtype
        minSeriesSize = nimages * dtypeFunc(dtype).itemsize

        splitsPerDim = _calcSplitsForBlockSize(blockSize, minSeriesSize, dims)
        strategy = cls(splitsPerDim, units="splits", **kwargs)
        strategy.setSource(images)
        return strategy

    @staticmethod
    def normalizeUnitsPerDim(unitsPerDim):
        unitsPerDim = map(int, unitsPerDim)
        if any((nsplits <= 0 for nsplits in unitsPerDim)):
            raise ValueError("All unit values must be positive; got " + str(unitsPerDim))
        return unitsPerDim

    def __validateUnitsPerDimForImage(self):
        dims = self.dims
        unitsPerDim, attrName = (self._splitsPerDim, "splitsPerDim") if \
            not (self._splitsPerDim is None) \
            else (self._pixPerDim, "pixelsPerDim")
        ndim = len(dims)
        if not len(unitsPerDim) == ndim:
            raise ValueError("%s length (%d) must match image dimensionality (%d); " %
                             (attrName, len(unitsPerDim), ndim) +
                             "have %s %s and image shape %s" % (attrName, str(unitsPerDim), str(dims)))

    @staticmethod
    def generateSlicesFromSplits(splitsPerDim, dims):
        # slices will be sequence of sequences of slices
        # slices[i] will hold slices for ith dimension
        slices = []
        for nsplits, dimSize in zip(splitsPerDim, dims):
            blockSize = dimSize / nsplits  # integer division
            blockRem = dimSize % nsplits
            start = 0
            dimSlices = []
            for blockIdx in xrange(nsplits):
                end = start + blockSize
                if blockRem:
                    end += 1
                    blockRem -= 1
                dimSlices.append(slice(start, min(end, dimSize), 1))
                start = end
            slices.append(dimSlices)
        return slices

    @staticmethod
    def generateSlicesFromPixels(pixPerDim, dims):
        # slices will be sequence of sequences of slices
        # slices[i] will hold slices for ith dimension
        slices = []
        for pix, dimSize in zip(pixPerDim, dims):
            start = 0
            dimSlices = []
            while start < dimSize:
                end = start + pix
                end = min(end, dimSize)
                dimSlices.append(slice(start, end, 1))
                start += pix
            slices.append(dimSlices)
        return slices

    def setSource(self, images):
        super(SimpleBlockingStrategy, self).setSource(images)
        self._nimages = images.nrecords
        self.__validateUnitsPerDimForImage()
        if not (self._splitsPerDim is None):
            self._slices = SimpleBlockingStrategy.generateSlicesFromSplits(self._splitsPerDim, self.dims)
        else:
            self._slices = SimpleBlockingStrategy.generateSlicesFromPixels(self._pixPerDim, self.dims)

    def calcAverageBlockSize(self):
        if not (self._splitsPerDim is None):
            elts = _BlockMemoryAsSequence.avgElementsPerBlock(self.dims, self._splitsPerDim)
        else:
            elts = reduce(lambda x, y: x * y, self._pixPerDim)
        return elts * dtypeFunc(self.dtype).itemsize * self.nimages

    def extractBlockFromImage(self, imgAry, blockSlices, timepoint, numTimepoints):
        # add additional "time" dimension onto front of val
        val = expand_dims(imgAry[blockSlices], axis=0)
        origShape = [numTimepoints] + list(imgAry.shape)
        imgSlices = [slice(timepoint, timepoint+1, 1)] + list(blockSlices)
        pixelsPerDim = self.pixelsPerDim
        return BlockGroupingKey(origShape, imgSlices, pixelsPerDim), val

    def blockingFunction(self, timePointIdxAndImageArray):
        tpIdx, imgAry = timePointIdxAndImageArray
        totNumImages = self.nimages
        slices = self._slices

        sliceProduct = itertools.product(*slices)
        for blockSlices in sliceProduct:
            yield self.extractBlockFromImage(imgAry, blockSlices, tpIdx, totNumImages)

    def combiningFunction(self, spatialIdxAndBlocksSequence):
        _, partitionedSequence = spatialIdxAndBlocksSequence
        # sequence will be of (partitioning key, np array) pairs
        ary = None
        firstKey = None
        for key, block in partitionedSequence:
            if ary is None:
                # set up collection array:
                newShape = [key.origShape[0]] + list(block.shape)[1:]
                ary = zeros(newShape, block.dtype)
                firstKey = key

            # put values into collection array:
            targSlices = [key.temporalKey] + ([slice(None)] * (block.ndim - 1))
            ary[targSlices] = block

        return firstKey.asTemporallyConcatenatedKey(), ary


class SeriesBlockingStrategy(BlockingStrategy):
    """A BlockingStrategy that recombines Series objects (with spatial indices x,y,z) into
    nonoverlapping, spatially-contiguous Blocks.
    """

    def __init__(self, splitsPerDim, **kwargs):
        """Returns a new SeriesBlockingStrategy.

        Parameters
        ----------
        splitsPerDim : n-tuple of positive int, where n = dimensionality of image
            Specifies that intermediate blocks are to be generated by splitting the i-th dimension
            of the image into splitsPerDim[i] roughly equally-sized partitions.
            1 <= splitsPerDim[i] <= self.dims[i]
        """
        super(SeriesBlockingStrategy, self).__init__()
        self._splitsPerDim = SimpleBlockingStrategy.normalizeUnitsPerDim(splitsPerDim)
        self._slicesProduct = None
        self._linIndices = None
        self._subToIndFcn = None

    def setSource(self, series):
        """Readies the BlockingStrategy to operate over the passed Series.

        This implementation will set .nimages from the length of the passed object's .index attribute.

        No return value.
        """
        super(SeriesBlockingStrategy, self).setSource(series)
        from lambdaimage.rdds.keys import _subToIndConverter
        # as we are currently doing in Series.saveAsBinarySeries, here we assume that len(series.index) is
        # equal to the length of a single record value. If not, we will probably end up in trouble downstream.
        self._nimages = len(series.index)
        self.__validateSplitsPerDimForSeries()
        slices = SimpleBlockingStrategy.generateSlicesFromSplits(self.splitsPerDim, self.dims)
        # flip slice ordering so that z index increments first
        reversedSlicesIter = itertools.product(*(slices[::-1]))
        self._slicesProduct = [sl[::-1] for sl in reversedSlicesIter]
        self._subToIndFcn = _subToIndConverter(self.dims, order='F', isOneBased=False)
        self._linIndices = self.generateMaxLinearIndicesForBlocksFromSlices()

    @property
    def splitsPerDim(self):
        return self._splitsPerDim

    @property
    def linearIndices(self):
        return self._linIndices

    @property
    def nblocks(self):
        if self._linIndices is None:
            raise ValueError("Must call strategy.setSource() before referencing strategy.nblocks")
        return len(self._linIndices)

    def getBlocksClass(self):
        return SimpleBlocks

    def __validateSplitsPerDimForSeries(self):
        dims = self.dims
        splitsPerDim = self.splitsPerDim
        ndim = len(dims)
        if not len(splitsPerDim) == ndim:
            raise ValueError("splitsPerDim length (%d) must match image dimensionality (%d); " %
                             (len(splitsPerDim), ndim) +
                             "have splitsPerDim %s and image shape %s" % (str(splitsPerDim), str(dims)))
        sawLastSplitDim = False
        splitsAndDims = zip(splitsPerDim, dims)
        for splits, dim in reversed(splitsAndDims):
            if splits > dim:
                raise ValueError("Cannot have a greater number of splits in a dimension than the size of that " +
                                 "dimension; got splits %s for dimension %s (%d > %d" %
                                 (str(splitsPerDim), str(dims), splits, dim))
            if sawLastSplitDim and splits > 1:
                raise ValueError("To recombine a Series into Blocks, only one dimension can be incompletely " +
                                 "split (splits < dimension size); all later dimensions must be completely " +
                                 "split (splits == dimension size) and all earlier dimension cannot be split at all " +
                                 "(splits == 1). Got splits %s for dimensions %s." % (str(splitsPerDim), str(dims)))
            if splits < dim:
                sawLastSplitDim = True

    def generateMaxLinearIndicesForBlocksFromSlices(self):
        linearIndices = []
        for blockSlices in self._slicesProduct:
            maxIdxs = []
            for slise, dimSize in zip(blockSlices, self.dims):
                maxIdx = slise.stop - 1 if slise.stop is not None else dimSize - 1  # maxIdx is inclusive
                maxIdxs.append(maxIdx)
            linearIdx = self._subToIndFcn(maxIdxs)
            linearIndices.append(linearIdx)
        linearIndices.sort()
        return linearIndices

    @classmethod
    def generateFromBlockSize(cls, series, blockSize, **kwargs):
        """Returns a new SeriesBlockingStrategy, that yields blocks
        closely matching the requested size in bytes.

        Parameters
        ----------
        series : Series object
            Series for which blocking strategy is to be generated.

        blockSize : positive int or string
            Requests an average size for the intermediate blocks in bytes. A passed string should
            be in a format like "256k" or "150M" (see util.common.parseMemoryString). If blocksPerDim
            or groupingDim are passed, they will take precedence over this argument. See
            strategy._BlockMemoryAsSequence for a description of the blocking strategy used.

        Returns
        -------
        SeriesBlockingStrategy or subclass
            new BlockingStrategy will be created and setSource() called on it with the passed series object
        """
        dims, nimages, dtype = series.dims, len(series.index), series.dtype
        elementSize = nimages * dtypeFunc(dtype).itemsize

        splitsPerDim = _calcSplitsForBlockSize(blockSize, elementSize, dims)
        strategy = cls(splitsPerDim, units="splits", **kwargs)
        strategy.setSource(series)
        return strategy

    def calcAverageBlockSize(self):
        if self._splitsPerDim is None:
            raise Exception("setSource() must be called before calcAverageBlockSize()")
        elts = _BlockMemoryAsSequence.avgElementsPerBlock(self.dims, self._splitsPerDim)
        return elts * dtypeFunc(self.dtype).itemsize * self.nimages

    def blockingFunction(self, seriesKeyAndValues):
        seriesKey, seriesValues = seriesKeyAndValues
        linearKey = self._subToIndFcn(seriesKey)
        linIdxs = self.linearIndices
        blockIdx = bisect.bisect_left(linIdxs, linearKey)
        if blockIdx >= len(linIdxs):
            raise Exception("Error: series linear key %d is greater than max expected key %d" %
                            (seriesKey, self.linearIndices[-1]))
        return blockIdx, seriesKeyAndValues

    def combiningFunction(self, blockNumAndCollectedSeries):
        blockNum, collectedSeries = blockNumAndCollectedSeries
        blockSlices = self._slicesProduct[blockNum]
        imgShape = [self.nimages] + list(self.dims)
        vecShape = [-1] + [1] * len(self.dims)  # needed to coerce vector broadcast to work
        key = BlockGroupingKey(tuple(imgShape), tuple([slice(0, self.nimages, 1)] + list(blockSlices)))
        aryShape = [self.nimages]
        arySpatialOffsets = []
        for blockSlice, refSize in zip(blockSlices, self.dims):
            start, stop, _ = getStartStopStep(blockSlice, refSize)
            aryShape.append(stop - start)
            arySpatialOffsets.append(start)

        ary = zeros(aryShape, dtype=self.dtype)
        for seriesKey, seriesAry in collectedSeries:
            arySlices = [slice(0, self.nimages)] + \
                        [slice(i-offset, i-offset+1) for (i, offset) in zip(seriesKey, arySpatialOffsets)]
            # this is an inefficient assignment,
            # since the first dimension of ary is not contiguous in memory:
            ary[arySlices] = seriesAry.reshape(vecShape)
        return key, ary


class PaddedBlockingStrategy(SimpleBlockingStrategy):
    def __init__(self, unitsPerDim, padding, units="pixels", **kwargs):
        super(PaddedBlockingStrategy, self).__init__(unitsPerDim, units=units, **kwargs)
        self._padding = self.__normalizePadding(padding)

    @property
    def padding(self):
        return self._padding

    def __normalizePadding(self, padding):
        # check whether padding is already sequence; if so, validate that it has the expected dimensionality
        unitsTuple, unitsName = (self._pixPerDim, "pixPerDim") if not (self._pixPerDim is None) \
            else (self._splitsPerDim, "splitsPerDim")
        try:
            lpad = len(padding)
        except TypeError:
            padding = [padding] * len(unitsTuple)
            lpad = len(padding)
        if not lpad == len(unitsTuple):
            raise ValueError("Padding tuple must be of equal size as %s tuple;" % unitsName +
                             " got '%s', must be length %d to match %s '%s'" %
                             (str(padding), len(self.splitsPerDim), unitsName, self.splitsPerDim))
        # cast to int and validate nonnegative
        padding = map(int, padding)
        if any((pad < 0 for pad in padding)):
            raise ValueError("All block padding must be nonnegative; got '%s'" % padding)
        return tuple(padding)

    def getBlocksClass(self):
        return PaddedBlocks

    @classmethod
    def generateFromBlockSize(cls, images, blockSize, padding=10, **kwargs):
        return super(PaddedBlockingStrategy, cls).generateFromBlockSize(images, blockSize, padding=padding, **kwargs)

    def extractBlockFromImage(self, imgAry, blockSlices, timepoint, numTimepoints):
        padSlices = []
        actualPadding = []
        for coreSlice, pad, l in zip(blockSlices, self.padding, imgAry.shape):
            # normalize 'None' values to appropriate positions
            normStart, normStop, normStep = getStartStopStep(coreSlice, l)
            start = max(0, normStart-pad)
            stop = min(l, normStop+pad)
            startPadSize = normStart - start
            stopPadSize = stop - normStop
            padSlices.append(slice(start, stop, normStep))
            actualPadding.append((startPadSize, stopPadSize))

        # calculate "core" slices into values array based on actual size of padding
        vals = imgAry[padSlices]
        coreValSlices = [slice(0, 1, 1)]  # start with slice for time
        for actualPad, l in zip(actualPadding, vals.shape):
            actualStartPad, actualStopPad = actualPad
            coreValSlices.append(slice(actualStartPad, l-actualStopPad, 1))

        # add additional "time" dimension onto front of val
        val = expand_dims(imgAry[padSlices], axis=0)
        origShape = [numTimepoints] + list(imgAry.shape)
        imgSlices = [slice(timepoint, timepoint+1, 1)] + list(blockSlices)
        padSlices = [slice(timepoint, timepoint+1, 1)] + padSlices
        return PaddedBlockGroupingKey(origShape, padSlices, imgSlices, tuple(val.shape),
                                      coreValSlices, self.pixelsPerDim), val


def _normDimsToShapeTuple(dims):
    """Returns a shape tuple from the passed object, which may be either already a tuple of int
    or a Dimensions object.
    """
    from lambdaimage.rdds.keys import Dimensions
    if isinstance(dims, Dimensions):
        return dims.count
    return dims


def _calcSplitsForBlockSize(blockSize, elementSize, dims):
    from lambdaimage.utils.common import parseMemoryString
    import bisect
    if isinstance(blockSize, basestring):
        blockSize = parseMemoryString(blockSize)

    memSeq = _BlockMemoryAsReversedSequence(_normDimsToShapeTuple(dims))
    tmpIdx = bisect.bisect_left(memSeq, blockSize / float(elementSize))
    if tmpIdx == len(memSeq):
        # handle case where requested block is bigger than the biggest image
        # we can produce; just give back the biggest block size
        tmpIdx -= 1
    return memSeq.indToSub(tmpIdx)


class _BlockMemoryAsSequence(object):
    """Helper class used in calculation of slices for requested blocks of a particular size.

    The blocking strategy represented by objects of this class is to split into N equally-sized
    subdivisions along each dimension, starting with the rightmost dimension.

    So for instance consider an Image with spatial dimensions 5, 10, 3 in x, y, z. The first nontrivial
    subdivision would be to split into 2 blocks along the z axis:
    splits: (1, 1, 2)
    In this example, downstream this would turn into two blocks, one of size (5, 10, 2) and another
    of size (5, 10, 1).

    The next subdivision would be to split into 3 blocks along the z axis, which happens to
    corresponding to having a single block per z-plane:
    splits: (1, 1, 3)
    Here these splits would yield 3 blocks, each of size (5, 10, 1).

    After this the z-axis cannot be split further, so the next subdivision starts splitting along
    the y-axis:
    splits: (1, 2, 3)
    This yields 6 blocks, each of size (5, 5, 1).

    Several other splits are possible along the y-axis, going from (1, 2, 3) up to (1, 10, 3).
    Following this we move on to the x-axis, starting with splits (2, 10, 3) and going up to
    (5, 10, 3), which is the finest subdivision possible for this data.

    Instances of this class represent the average size of a block yielded by this blocking
    strategy in a linear order, moving from the most coarse subdivision (1, 1, 1) to the finest
    (x, y, z), where (x, y, z) are the dimensions of the array being partitioned.

    This representation is intended to support binary search for the blocking strategy yielding
    a block size closest to a requested amount.
    """
    def __init__(self, dims):
        self._dims = dims

    def indToSub(self, idx):
        """Converts a linear index to a corresponding blocking strategy, represented as
        number of splits along each dimension.
        """
        dims = self._dims
        ndims = len(dims)
        sub = [1] * ndims
        for dIdx, d in enumerate(dims[::-1]):
            dIdx = ndims - (dIdx + 1)
            delta = min(dims[dIdx]-1, idx)
            if delta > 0:
                sub[dIdx] += delta
                idx -= delta
            if idx <= 0:
                break
        return tuple(sub)

    @staticmethod
    def avgElementsPerBlock(imageShape, splitsPerDim):
        """Calculates the average number of elements per block, defined by the passed sequence of splits
        applied to an array of the passed shape
        """
        sz = [d / float(s) for (d, s) in zip(imageShape, splitsPerDim)]
        return reduce(lambda x, y: x * y, sz)

    def __len__(self):
        return sum([d-1 for d in self._dims]) + 1

    def __getitem__(self, item):
        splits = self.indToSub(item)
        return _BlockMemoryAsSequence.avgElementsPerBlock(self._dims, splits)


class _BlockMemoryAsReversedSequence(_BlockMemoryAsSequence):
    """A version of _BlockMemoryAsSequence that represents the linear ordering of splits in the
    opposite order, starting with the finest blocking scheme allowable for the array dimensions.

    This can yield a sequence of block sizes in increasing order, which is required for binary
    search using python's 'bisect' library.
    """
    def _reverseIdx(self, idx):
        l = len(self)
        if idx < 0 or idx >= l:
            raise IndexError("list index out of range")
        return l - (idx + 1)

    def indToSub(self, idx):
        return super(_BlockMemoryAsReversedSequence, self).indToSub(self._reverseIdx(idx))
