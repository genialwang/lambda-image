import os
from pyspark import SparkContext, SparkConf
from lambdaimage import lambdaimageContext
from lambdaimage.imgprocessing.deconvolution import Deconvolution
import time

input='/home/wb/data/deconv/'
#input='/home/wb/data/fs_3d/'
output='/home/wb/data/local/re_2d/'
#output='/home/wb/data/local/re_3d/'

def fs_in_out(input, output):
    in_list = []
    out_list = []
    directorys = []
    directorys.append(input)
    for root, dirs, files in os.walk(input):
        directorys += [(root+file_dirs) for file_dirs in dirs]

    for i in range(len(directorys)):
        in_list.append(directorys[i]+'/*.tif')

    for i in range(len(directorys)):
        denoise=output+directorys[i][len(input):]
        out_list.append(denoise)
        if not os.path.exists(denoise):
            os.makedirs(denoise)

    return (in_list, out_list)

if __name__=='__main__':
    inlist, outlist=fs_in_out(input, output) 

    conf = SparkConf().setAppName('test')
    tsc=lambdaimageContext.start(conf=conf)

    reg=Deconvolution('rl')
    #iters=[100, 150, 200, 250]
    iters=[5]
    for iter in iters:
        #reg.prepare("/home/jph/test/PSF_2d.tif", iter)
        #reg.prepare("/home/jph/graduate_test/Version/Spark/fs_2d/PSF_50.tif", iter)
        reg.prepare("/home/wb/data/deconv/PSF.tif", iter)
        #reg.prepare("/home/wb/data/fs_3d/PSF_3d.tif", iter)
        
        for i in range(len(inlist)):
            try:
                imIn=tsc.loadImages(inlist[i], inputFormat='tif-stack')
                t_start=time.time()
                result=reg.run(imIn)
                result.exportAsTiffs(outlist[i], overwrite=True)
                #imIn.exportAsTiffs(outlist[i], overwrite=True)
                t_end=time.time()
                print 'spark local image: ', inlist[i][len(input):], 'iter: ', iter, ' time: ', (t_end-t_start)
            except BaseException, e:
                print 'error ', inlist[i]
